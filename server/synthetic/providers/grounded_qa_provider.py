"""Grounded QA eval-row generation through the LiteLLM gateway.

For every selected source chunk the generator alias is asked for question /
answer rows that each carry a verbatim ``evidence_quote``. A row survives only
when the quote is found in the source excerpt (whitespace-, case- and
quote-mark-insensitive), the expected answer's content words are anchored in
that excerpt, and the question is self-contained (no references to "this
email"/"the excerpt", and at least one searchable anchor such as a name, date,
number, quoted phrase or address). Survivors are rated by the configured judge
alias (``system_prompts.synthetic_judge``) when curation is enabled; rows under
the curation threshold are dropped.

There is no deterministic fallback: a gateway failure fails the run, a row the
model could not ground is rejected, cancellation aborts in-flight gateway calls,
and a run that keeps nothing fails its quality gate downstream. The local
single-stream serving alias is serialized process-wide, not per run.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import re
import unicodedata
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, TypeVar

from server.chat.generation import generate_chat_text
from server.chat.provider_router import ProviderRoute
from server.evaluation.text_tokens import has_cjk, normalize_text, phrase_in, tokens
from server.gateway_catalog import gateway_rows_snapshot
from server.models.tribrid_config_model import (
    Chunk,
    EvalDatasetItem,
    SyntheticArtifactKind,
    SyntheticGeneratorConfig,
    SyntheticRunStartRequest,
    SyntheticRunSummary,
    TriBridConfig,
)
from server.synthetic.recipes import (
    _autotune_patch,
    _chunk_to_summary,
    _derive_keywords,
    _infer_source_kind,
    resolve_synthetic_route,
    select_source_chunks,
)

PROVIDER_NAME = "grounded_qa"
LOCAL_SERVING_PROVIDER = "ragweld"
EVAL_RECIPES = frozenset({"eval_dataset", "triplets", "autotune_retrieval", "full_stack"})
ANSWER_ANCHOR_MIN_FRACTION = 0.5

ProgressCallback = Callable[[str, float | None], Awaitable[None]]
T = TypeVar("T")


class GroundedQAParseError(ValueError):
    """The model did not return the JSON shape the prompt demands."""


class GroundedQAGenerationError(RuntimeError):
    """The generator or judge route failed; the run must fail, never degrade."""


_FENCE_RE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*|\s*```\s*$", re.MULTILINE)
_WS_RE = re.compile(r"\s+")
_QUOTE_TRANSLATION = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        " ": " ",
    }
)
_SELF_REFERENCE_RE = re.compile(
    r"\b(this|that|these|those)\s+(e-?mail|document|excerpt|text|message|passage|source|file|snippet|thread|note|memo|letter|attachment|transcript|page)s?\b"
    r"|\bthe\s+(excerpt|passage|snippet|source\s+text|provided\s+text|text\s+above|document\s+above|email\s+above)\b"
    r"(?!\s+(from|by|dated)\s+(?:the\s+)?(?-i:[A-Z0-9\"“'‘]))"
    # "the attached/provided/following ... email": a source the reader is assumed to be holding
    r"|\bthe\s+(attached|provided|supplied|following|preceding|given|included|enclosed|quoted|accompanying|pasted|shared|selected|current|present|above|below)\s+"
    r"(e-?mail|document|excerpt|text|message|passage|source|file|snippet|thread|note|memo|letter|attachment|transcript|page|content|material)s?\b"
    r"|\b(mentioned|quoted|shown|described|referenced|listed|provided|given)\s+(above|below|here)\b"
    r"|\baccording\s+to\s+the\s+(excerpt|passage|text|source|document|snippet|e-?mail|message|attachment)\b"
    r"(?!\s+(from|by|dated)\s+(?:the\s+)?(?-i:[A-Z0-9\"“'‘]))"
    r"|\b(in|from|per)\s+the\s+(excerpt|passage|snippet|source|attachment)\b"
    r"(?!\s+(from|by|dated)\s+(?:the\s+)?(?-i:[A-Z0-9\"“'‘]))"
    # bare discourse reference: "what does the email say about X?" names no document, only "the" one at hand
    r"|\b(what|who|whom|whose|when|where|why|how|which)\b[^?]*?\b(does|did|do|is|was|are|were|has|have|had|will|would|can|could|should|might)?\s*the\s+"
    r"(e-?mail|document|message|text|passage|excerpt|note|memo|letter|file|transcript|page|attachment|thread|record|report)"
    r"(\s+(from|by|to|of)\s+(?!(?:the\s+)?(?-i:[A-Z0-9\"“'‘]))\S+|\s+(about|concerning|regarding|on)\s+[^?]*?)?\s+"  # "the email from him / about X say" is still bare
    r"(say|says|said|state|states|stated|mention|mentions|mentioned|tell|tells|told|describe|describes|described|indicate|indicates|indicated"
    r"|show|shows|showed|report|reports|reported|claim|claims|claimed|contain|contains|contained|discuss|discusses|discussed|suggest|suggests|suggested"
    r"|explain|explains|explained|reveal|reveals|revealed|imply|implies|implied|recommend|recommends|recommended|list|lists|listed|name|names|named"
    r"|identify|identifies|identified|specify|specifies|specified|confirm|confirms|confirmed|note|notes|noted)\b"
    # "in/from the email ..." is a bare reference unless the document itself is identified right after
    # ("the email from Barry Cohen", "the memo dated 2017-10-03", "the letter to Cohen")
    r"|\b(in|from|per|within|of)\s+the\s+(e-?mail|document|message|text|passage|excerpt|note|memo|letter|file|transcript|page|attachment|thread|record|report)"
    # (the whole pattern is case-insensitive; the identifier class must not be: "from him" is not an identifier)
    r"(?!\s+(from|by|of|to|dated|sent|written|addressed|signed|between)\s+(?:the\s+)?(?-i:[A-Z0-9\"“'‘]))"
    r"|\b(above|below)\s*\?$"
    # Explicit, non-exhaustive equivalents in other languages; the judge is the second line.
    r"|这封(邮件|信|电子邮件)|这份(文件|文档|报告|材料|资料)|这段(文字|话|文本)|这篇(文章|报告|文档)|这个(文件|文档|附件)"
    r"|本(报告|文件|文档|邮件|文章|段落|材料|资料|记录|信件|附件|文)(?!田)|上文|上述|以上(内容|文字)"
    r"|根据(这封|这份|这段|这篇|这个|本|上文|上述|以上)(邮件|信|文件|文档|报告|文字|话|文本|文章|附件|材料|资料|内容)"
    r"|這封(郵件|信)|這份(文件|文檔|報告|材料|資料)|這段(文字|話)|這篇(文章|報告)|這個(文件|文檔|附件)"
    r"|本(報告|文件|文檔|郵件|文章|段落|材料|資料|記錄|信件|附件)"
    r"|根據(這封|這份|這段|這篇|這個|本|上文|上述|以上)(郵件|信|文件|文檔|報告|文字|話|文本|文章|附件|材料|資料|內容)"
    r"|この(メール|文書|文章|手紙|テキスト|資料)|上記|前述|本文(中|によると)"
    r"|이\s?(이메일|메일|문서|글)|위의|상기|본문"
    r"|هذه\s+(الرسالة|الوثيقة|الرساله)|هذا\s+(البريد|المستند|النص|المقتطف)|أعلاه|اعلاه|وفق(ا|ًا)\s+لهذ"
    r"|(מייל|מסמך|טקסט|מכתב)\s+זה|ה(מייל|מסמך|טקסט|מכתב)\s+הזה|לעיל|על\s+פי\s+ה(מסמך|טקסט|מייל)"
    r"|\b(это|этом|этого|этому)\s+(письм[оаеу]|документ[аеу]?|текст[аеу]?|сообщени[еияю]|отрывк[аеу]?|фрагмент[аеу]?)\b"
    r"|\bсогласно\s+(этому|данному|тексту|документу|отрывку|письму)\b|\bв\s+тексте\s+выше\b"
    r"|\b(указан|упомянут|приведён|приведен|описан|процитирован)[а-яё]*\s+(выше|ниже)\b|\bвыше\s*\?$"
    r"|\b(este|esta)\s+(correo|mensaje|documento|texto|fragmento|extracto|carta)\b|\bsegún\s+el\s+(texto|fragmento|documento|extracto|correo)\b|\barriba\s*[?¿]?$"
    r"|\b(ce|cet|cette)\s+(courriel|e-?mail|mail|message|document|texte|extrait|lettre)\b|\bci-dessus\b|\bd'après\s+(le|l'|ce)\s?(texte|extrait|document|courriel|message)\b"
    r"|\b(diese|dieser|diesem|dieses)\s+(e-?mail|nachricht|dokument|text|auszug|brief)\b|\blaut\s+(dem|diesem)\s+(text|auszug|dokument)\b|\boben\s+(genannt|erwähnt|stehend)\b"
    r"|\b(este|esta|questo|questa|quest')\s?(e-?mail|mensagem|documento|texto|trecho|messaggio|testo|estratto)\b",
    re.IGNORECASE,
)
# A searchable anchor: a capitalized word after the first token that is not a
# pronoun/question word, a number, a quoted phrase, or an e-mail address.
# Pronoun-only questions have none.
# Anchor candidates in any script: an e-mail address, a quoted phrase, a number, or a
# word that is not sentence-initial (its first letter is checked for upper case in code,
# which works for every cased script: Latin, Cyrillic, Greek, accented letters). The
# e-mail alternative comes first so a local part is not consumed as a plain word.
_ANCHOR_CANDIDATE_RE = re.compile(
    r"(?P<email>\b[\w.+-]+@[\w-]+\.[\w.-]+\b)"
    r"|(?P<quote>(?<!\w)[\"“'‘][^\"”'’]{2,}[\"”'’])"  # a quoted phrase; a possessive apostrophe does not open one
    r"|(?P<number>(?<![0-9A-Za-z_])\d[\d:/.-]*(?![0-9A-Za-z_]))"  # not \b: CJK letters are \w, so 在2017年 must still anchor
    r"|(?P<word>(?<!^)(?<![.!?]\s)\b[^\W\d_][\w'’.-]*)",
    re.UNICODE,
)
_NON_ANCHOR_WORDS = frozenset(
    {
        # question words of the supported cased languages (they follow ¿ / « / ( mid-string)
        "qué", "que", "quién", "quien", "quiénes", "cuál", "cual", "cuáles", "cuándo", "cuando", "dónde", "donde", "cómo", "como",
        "por", "quel", "quelle", "quels", "quelles", "qui", "quand", "où", "ou", "comment", "pourquoi", "lequel", "laquelle",
        "was", "wer", "wen", "wem", "wessen", "wann", "wo", "wie", "warum", "wieso", "welche", "welcher", "welches", "welchen",
        "che", "chi", "quale", "quali", "quando", "dove", "come", "perché", "perche", "cosa",
        "что", "кто", "кого", "кому", "когда", "где", "куда", "как", "почему", "зачем", "какой", "какая", "какое", "какие", "который",
        "которая", "которое", "которые", "чем", "чём", "чего", "сколько", "откуда",
        "quem", "qual", "quais", "onde", "porque", "porquê", "o", "a", "em", "de", "quê",
        "quanto", "quanta", "quantos", "quantas", "aonde", "cadê", "cuánto", "cuánta", "cuántos", "cuántas",
        "combien", "wieviel", "quanti", "quante", # calendar words: "in October" anchors a time, never the subject of the question
        "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
        "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "januar", "februar", "märz", "mai", "juni", "juli", "oktober", "dezember", "montag", "dienstag", "mittwoch",
        "donnerstag", "freitag", "samstag", "sonntag", "today", "yesterday", "tomorrow", "tonight",
        "janvier", "février", "fevrier", "mars", "avril", "juin", "juillet", "août", "aout", "septembre", "octobre",
        "novembre", "décembre", "decembre", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
        "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "setiembre", "octubre",
        "noviembre", "diciembre", "lunes", "martes", "miércoles", "miercoles", "jueves", "viernes", "sábado", "sabado", "domingo",
        "gennaio", "febbraio", "aprile", "maggio", "giugno", "luglio", "settembre", "ottobre", "dicembre",
        "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica",
        "janeiro", "fevereiro", "março", "maio", "junho", "julho", "setembro", "outubro", "novembro", "dezembro",
        "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "hier", "demain", "aujourd'hui", "ayer", "mañana", "hoy", "ieri", "domani", "oggi", "ontem", "amanhã", "hoje",
        "heute", "gestern", "morgen", "вчера", "сегодня", "завтра",
        *[
            stem + ending
            for stem in ("январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр")
            for ending in ("ь", "я", "ю", "е", "ем", "й", "я", "ям", "ями", "ях", "а", "у", "ом", "ы", "ов", "ам", "ами", "ах")
        ],
        *[
            stem + ending
            for stem in ("понедельник", "вторник", "сред", "четверг", "пятниц", "суббот", "воскресень")
            for ending in ("", "а", "у", "ом", "е", "и", "ы", "ам", "ами", "ах", "ой", "ы", "у", "е", "я", "ю", "ем")
        ],
        "he", "she", "it", "they", "them", "him", "her", "his", "hers", "its", "their", "theirs", "we", "us",
        "our", "you", "your", "i", "me", "my", "who", "whom", "whose", "what", "which", "when", "where", "why",
        "how", "did", "does", "do", "were", "is", "are", "the", "an", "and", "or", "but", "if",
        "this", "that", "these", "those", "there", "here", "then", "than",
    }
)
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "that", "with", "this", "from", "was", "were", "are", "his", "her", "its",
        "their", "they", "them", "had", "has", "have", "not", "but", "said", "say", "says", "who", "what",
        "which", "when", "where", "why", "how", "did", "does", "than", "then", "into", "onto", "about",
        "would", "could", "should", "will", "also", "any", "all", "one", "two", "per", "via", "you", "your",
        "on", "in", "at", "of", "to", "by", "as", "is", "be", "an", "or", "it", "he", "she", "we", "us",
    }
)

_LOCAL_ALIAS_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", str(text or "")).strip()


def _extract_json(text: str, *, opener: str, closer: str) -> str:
    stripped = _strip_fences(text)
    start = stripped.find(opener)
    end = stripped.rfind(closer)
    if start < 0 or end < 0 or end <= start:
        raise GroundedQAParseError(f"no JSON {opener}{closer} payload in model output")
    return stripped[start : end + 1]


def parse_generated_rows(text: str) -> list[dict[str, Any]]:
    """Parse the generator output: a JSON array of row objects (optionally fenced or wrapped in {"rows": [...]})."""
    stripped = _strip_fences(text)
    candidates: list[str] = []
    first_array = stripped.find("[")
    first_object = stripped.find("{")
    if first_object >= 0 and (first_array < 0 or first_object < first_array):
        candidates.append(_extract_json(stripped, opener="{", closer="}"))
    if first_array >= 0:
        candidates.append(_extract_json(stripped, opener="[", closer="]"))
    if not candidates:
        raise GroundedQAParseError("generator output contained no JSON")

    payload: Any = None
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
            break
        except json.JSONDecodeError as exc:
            last_error = exc
    if payload is None:
        raise GroundedQAParseError(f"generator output is not valid JSON: {last_error}")

    if isinstance(payload, dict):
        for key in ("rows", "items", "questions", "pairs"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            raise GroundedQAParseError("generator output object has no rows array")
    if not isinstance(payload, list):
        raise GroundedQAParseError("generator output is not a JSON array")
    rows: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            raise GroundedQAParseError("generator output array contains a non-object row")
        rows.append(row)
    return rows


def _normalize_for_grounding(text: str) -> str:
    folded = unicodedata.normalize("NFKC", str(text or "")).translate(_QUOTE_TRANSLATION)
    return _WS_RE.sub(" ", folded).strip().casefold()


def is_grounded(evidence_quote: str, source_excerpt_text: str) -> bool:
    quote = _normalize_for_grounding(evidence_quote)
    if not quote:
        return False
    return quote in _normalize_for_grounding(source_excerpt_text)


def answer_is_anchored(expected_answer: str, source_excerpt_text: str) -> bool:
    """At least half of the answer's content words must appear as whole tokens in the excerpt.

    CJK answers (no whitespace word boundaries) are anchored by normalized substring
    containment instead.
    """
    answer_tokens = [
        t for t in tokens(_normalize_for_grounding(expected_answer)) if len(t) >= 2 and t not in _STOPWORDS
    ]
    if not answer_tokens:
        return False
    if has_cjk(expected_answer):
        return normalize_text(_normalize_for_grounding(expected_answer)) in normalize_text(
            _normalize_for_grounding(source_excerpt_text)
        )
    excerpt_tokens = set(tokens(_normalize_for_grounding(source_excerpt_text)))
    present = sum(1 for token in answer_tokens if token in excerpt_tokens)
    return present / len(answer_tokens) >= ANSWER_ANCHOR_MIN_FRACTION


_INITIAL_WORD_RE = re.compile(r"^[^\w]*(?P<word>[^\W\d_][\w'’.-]*)", re.UNICODE)  # skips ¿ « ( before the first word
_TITLE_RE = re.compile(
    r"\s*[,\-—–(]?\s*\b(?:titled|entitled)\s+(?P<title>\"[^\"]+\"|“[^”]+”|'[^']+'|‘[^’]+’|.+?)"  # not named/called: those are also verbs
    r"(?=\s*[,?)]|\s+(?:say|says|said|mention|mentions|mentioned|state|states|stated|describe|describes|described|show|shows|showed"
    r"|report|reports|reported|list|lists|listed|contain|contains|contained|discuss|discusses|discussed|which|what|who|whom|when|where|why|how)\b|$)",
    re.IGNORECASE,
)
_QUOTE_CHARS = "\"“”'‘’"


def _quoted_content_tokens(quoted: str) -> list[str]:
    return [t for t in tokens(quoted.strip(_QUOTE_CHARS)) if t not in _NON_ANCHOR_WORDS and t not in _STOPWORDS]


# Subject pronouns only: "their emissions" is an object/possessive and leaves the subject
# ("Which 2017 regulation") free to be identified by its number.
_PRONOUN_SUBJECT_RE = re.compile(
    r"\b(he|she|they|it|i|we|you)\b"
    r"|\b(он|она|они|оно|я|мы|вы|ты)\b"
    r"|\b(er|sie|es|ich|wir|ihr)\b"
    r"|\b(il|elle|ils|elles|je|nous|vous|tu)\b"
    r"|\b(él|ella|ellos|ellas|yo|nosotros|nosotras|vosotros|usted|ustedes)\b"
    r"|\b(هو|هي|هم|هن|أنا|انا|نحن|أنت|انت|أنتم|انتم)\b"
    r"|\b(הוא|היא|הם|הן|אני|אנחנו|אתה|את|אתם)\b"
    r"|[他她它們们牠]|彼女|彼ら|彼|私|僕|俺|自分|自身|あなた|かれ|かのじょ|わたし"
    r"|그녀|그들|그는|그가|자신|자기|당신|우리|나는|내가|저는",
    re.IGNORECASE | re.UNICODE,
)


_SUBJECT_WINDOW_TOKENS = 4
_TOKEN_SPAN_RE = re.compile(r"[^\W_]+", re.UNICODE)
# English: the subject of an interrogative clause follows its auxiliary ("did he", "was she",
# "have they"), wherever that clause sits ("Which of the 2017 regulations did he enforce?").
_EN_AUX_SUBJECT_RE = re.compile(
    r"\b(did|does|do|is|was|are|were|has|have|had|will|would|can|could|should|might|must|shall)\s+(?P<pronoun>he|she|they|it|i|we|you)\b"
    r"(?!\s+(that|who|which|whom)\b)",  # "was it that …" is a cleft; longer cleft focuses are handled by _is_cleft_it
    re.IGNORECASE,
)
# (5) a nominative pronoun after a reporting verb is the subject of the embedded clause
# ("Which statement said he called …"): it needs an antecedent like any other subject.
_EN_REPORT_SUBJECT_RE = re.compile(
    r"\b(say|said|says|claim|claimed|claims|report|reported|reports|state|stated|states|think|thought|thinks|believe|believed"
    r"|confirm|confirmed|confirms|mention|mentioned|mentions|note|noted|notes|argue|argued|argues|write|wrote|writes)\s+(?P<pronoun>he|she|they|it|i|we|you)\b",
    re.IGNORECASE,
)
_PERSON_PRONOUNS = frozenset({"he", "she", "him", "her"})
# "is/was it <focus> that/who/which …": the focus may be anything bounded (a noun phrase, a
# prepositional phrase, "because of …"); expletive `it` is not a subject.
_EN_CLEFT_RE = re.compile(
    r"\b(is|was)\s+(?P<it>it)\s+(?:[^?,]{1,80}?\s+)?(that|who|which|whom)\b",  # "Was it Barry Cohen?" is not a cleft
    re.IGNORECASE,
)


def _is_cleft_it(question: str, position: int) -> bool:
    """True when the `it` at `position` is the expletive of an "is/was it … that/who" cleft —
    that occurrence only, not any `it` in a question that has a cleft somewhere later."""
    return any(match.start("it") == position for match in _EN_CLEFT_RE.finditer(question))
# Possessive determiners whose owner is not named in the question ("What was his balance?",
# 他的名字). A possessive is resolved when a nominal antecedent precedes it ("companies … their").
_POSSESSIVE_RE = re.compile(
    r"\b(his|her|their|its|my|our|your)\b"
    r"|\b(его|её|ее|их|sein|seine|seiner|seinen|seinem|ihr|ihre|ihrer|ihren|ihrem|son|sa|ses|leur|leurs|su|sus)\b"
    r"|(他|她|它|他们|她们|它们|他們|她們)的|(彼|彼女|彼ら|自分)の|(그|그녀|그들)의",
    re.IGNORECASE | re.UNICODE,
)


def _has_pronominal_subject(question: str) -> bool:
    """The question's subject is an UNRESOLVED pronoun: it opens the question ("他在…", "그는 …",
    "Кто … он"), or — in English — follows the clause auxiliary ("What did he …", "… did he
    enforce?") with no antecedent before it; a person pronoun (he/she) needs a named person
    before it, it/they any content noun. A pronoun after a reporting verb ("did the agency say
    it enforced") is an object, and an unresolved possessive ("his balance", 他的名字) leaves the
    subject equally undefined."""
    if _has_unresolved_possessive(question):
        return True
    for pattern in (_EN_AUX_SUBJECT_RE, _EN_REPORT_SUBJECT_RE):
        for match in pattern.finditer(question):
            if match.group("pronoun").casefold() == "it" and _is_cleft_it(question, match.start("pronoun")):
                continue
            if not _has_antecedent(question[: match.start("pronoun")], match.group("pronoun")):
                return True
    # a pronoun among the first tokens of the question (offsets from the original string, never a
    # substring search: "Shepherd" contains "he")
    head_end = _head_window_end(question)
    for pronoun in _PRONOUN_SUBJECT_RE.finditer(question):
        if pronoun.start() >= head_end:
            break
        if pronoun.group(0).casefold() == "it" and _is_cleft_it(question, pronoun.start()):
            continue  # "Was it … that …": expletive it (this occurrence only)
        if not _has_antecedent(question[: pronoun.start()], pronoun.group(0)):
            return True
    return False


def _head_window_end(question: str) -> int:
    """Character offset just after the question's first `_SUBJECT_WINDOW_TOKENS` word tokens."""
    count = 0
    for match in _TOKEN_SPAN_RE.finditer(question):
        count += 1
        if count == _SUBJECT_WINDOW_TOKENS:
            return match.end()
    return len(question)


def _has_antecedent(before: str, pronoun: str) -> bool:
    """Something before the pronoun that it can refer to: a named person for he/she (a
    capitalized non-initial word, a content ideograph, or an interrogative animate role —
    "Who …", "Which witness …", "Which pilot …"), any content noun for it/they. Verb forms
    ("happened") are never antecedents."""
    person = pronoun.casefold() in _PERSON_PRONOUNS
    words = before.split()
    nominal: list[str] = []  # content words in order; the last one is the governing head noun
    for index, raw in enumerate(words):
        word = raw.strip("\"“”'‘’.,;:()[]")
        if not word:
            continue
        folded = word.casefold()
        if folded == "who":
            return True  # "Who said he …": the interrogative subject binds the pronoun
        if folded in _NON_ANCHOR_WORDS or folded in _STOPWORDS or _PRONOUN_SUBJECT_RE.fullmatch(folded) or folded.isdigit():
            continue
        if folded in _ANIMATE_ROLES:
            nominal.append(folded)  # "king" is a role, whatever its ending
            continue
        if _VERB_FORM_RE.match(word) or folded in _ANIMATE_VERBS:
            continue  # "happened", "changing", "said": not a noun
        if word[:1].isupper() and (index > 0 or raw.rstrip().endswith((":", ",", ";", "—", "-"))):
            return True  # a name ("Jeffrey Cohen …", "Cohen: why did he …")
        nominal.append(folded)
    if nominal and nominal[-1] in _ANIMATE_ROLES:
        return True  # "Which witness said he …" / "Which pilot … his": the head noun is a person
    if not person and nominal:
        return True  # "the agency … it", "companies … they"
    return _uncased_antecedent(before, person=person)


def _uncased_antecedent(before: str, *, person: bool) -> bool:
    """CJK/Korean: a content span that could be a name (two or more content ideographs, or a
    hangul stem of two or more syllables that is not grammar) precedes the pronoun. Whether
    that span is a person (张伟) or a thing (飞机) is not decidable without a lexicon; the
    judge is the authority for that distinction (documented residual)."""
    del person
    runs = _CJK_RUN_RE.findall(normalize_text(before))
    for run in runs:
        for i in range(len(run) - 1):
            if _is_cjk_content_span(run[i : i + 2]):
                return True
    for word in tokens(before):
        if _HANGUL_RE.search(word) and not any(ch.isdigit() for ch in word):
            stem = _hangul_stem(word)
            if len(stem) >= 2 and stem not in _HANGUL_FUNCTION_WORDS and not _is_hangul_predicate(word):
                return True
    return False


# Possessives that name a HUMAN owner. Grammatical-gender possessives (French son/sa/ses, Spanish
# su/sus, German sein/ihr, Russian его/её/их) agree with the owner's gender, not its humanity,
# so they only need some nominal antecedent ("Quelle entreprise a changé son siège").
_PERSON_POSSESSIVES = frozenset({"his", "her", "my", "our", "your", "他的", "她的", "彼の", "彼女の", "自分の", "그의", "그녀의"})
# Interrogative subjects that bind a person pronoun in an embedded clause: "Who said he …",
# "Which witness said he …", "Which pilot changed his route?" — an explicit role list, no parser.
_ANIMATE_ROLES = frozenset(
    "witness pilot officer agent lawyer attorney assistant manager employee executive director secretary person man woman "
    "official investigator author sender recipient driver captain doctor nurse engineer operator client customer buyer seller "
    "owner partner colleague friend passenger contact staffer member leader head chief president ceo cfo founder analyst broker "
    "banker trader accountant consultant contractor teacher student professor journalist reporter editor judge juror defendant "
    "plaintiff victim suspect detective spokesperson representative delegate ambassador minister senator governor mayor king "
    "queen prince princess guest host speaker caller applicant candidate nominee appointee employer worker technician scientist "
    "researcher physician surgeon dentist pharmacist therapist counsellor counselor coach player athlete musician artist actor "
    "actress writer poet historian economist politician diplomat soldier general colonel major sergeant commander admiral "
    "secretary treasurer chairman chairwoman chairperson boss supervisor intern trainee apprentice tenant landlord neighbour "
    "neighbor relative parent father mother son daughter brother sister husband wife spouse uncle aunt cousin grandfather "
    "grandmother child boy girl baby".split()
)
_VERB_FORM_RE = re.compile(r"^[^\W\d_]+(ed|ing)$", re.IGNORECASE)
_ANIMATE_VERBS = frozenset(
    "say said says claim claims report reports state states think thinks believe believes confirm confirms mention mentions "
    "note notes argue argues write writes wrote tell tells told ask asks call calls change changes enforce enforces".split()
)


def _has_unresolved_possessive(question: str) -> bool:
    """Every possessive needs an antecedent of the right kind before it: a person (named) for
    his/her and the non-English person forms, any content noun for its/their. One resolved
    `their` does not excuse a later unresolved `his`."""
    for match in _POSSESSIVE_RE.finditer(question):
        form = match.group(0).casefold()
        pronoun = "he" if form in _PERSON_POSSESSIVES else "it"
        if not _has_antecedent(question[: match.start()], pronoun):
            return True
    return False


def _identified_by_title(question: str, source_excerpt: str | None) -> bool:
    """Every bare source reference in the question is immediately identified by a meaningful title
    that the (non-empty) source carries: "the excerpt titled Aurora Calibration Log". A title
    attached to a different noun ("… the memo entitled X") does not identify "the excerpt"."""
    if not source_excerpt:
        return False
    found = False
    for match in _SELF_REFERENCE_RE.finditer(question):
        found = True
        title = _TITLE_RE.match(question, match.end())
        if title is None:
            return False
        name = title.group("title").strip(_QUOTE_CHARS + " ")
        if not _quoted_content_tokens(name) or not phrase_in(name, source_excerpt):
            return False
    return found


def _has_anchor(question: str, source_excerpt: str | None = None) -> bool:
    """A structural anchor: an address or number in any script; a quoted phrase that carries
    content words (and, when the source is known, occurs in it); a capitalized non-initial
    word in a cased script that is not a pronoun/question word; or a capitalized sentence-
    initial word that is not a question/function word and occurs in the source."""
    pronominal = _has_pronominal_subject(question)
    initial = _INITIAL_WORD_RE.match(question.strip())
    initial_span = (initial.start("word"), initial.end("word")) if initial is not None else None
    offset = len(question) - len(question.lstrip())
    title = _TITLE_RE.search(question)
    if title is not None:
        # "the excerpt titled e.e. cummings": the title identifies the source whatever its case
        name = title.group("title").strip(_QUOTE_CHARS + " ")
        if _quoted_content_tokens(name) and (source_excerpt is None or phrase_in(name, source_excerpt)):
            return True
    for match in _ANCHOR_CANDIDATE_RE.finditer(question):
        kind = match.lastgroup
        token = match.group(0)
        if kind == "word" and initial_span is not None and (match.start() - offset, match.end() - offset) == initial_span:
            continue  # sentence-initial (after ¿ « ( too): handled by the source-backed rule below
        if kind == "quote":
            if not _quoted_content_tokens(token):
                continue  # "'it'" names nothing
            if source_excerpt is not None and not phrase_in(token.strip(_QUOTE_CHARS), source_excerpt):
                continue
            return True
        if kind == "number":
            if pronominal:
                continue  # "What did he do in October 2017?": a date anchors time, not a pronominal subject
            return True
        if kind != "word":
            return True
        if not token[0].isupper():
            continue  # an ordinary mid-sentence word in a cased script is not a name
        if token.strip("'’.-").casefold() in _NON_ANCHOR_WORDS:
            continue
        return True
    if source_excerpt and initial is not None:
        word = initial.group("word").strip("'’.-")
        if word[:1].isupper() and word.casefold() not in _NON_ANCHOR_WORDS and _capitalized_mid_sentence(word, source_excerpt):
            return True  # "Aurora recorded what salinity ...?" when the source writes "the Aurora buoy"
    return False


def _capitalized_mid_sentence(word: str, text: str) -> bool:
    """True when `text` uses `word` with its capital letter somewhere other than a sentence start:
    proper nouns keep their capital mid-sentence, ordinary sentence-initial verbs do not."""
    pattern = re.compile(r"(?<!^)(?<![.!?。！？]\s)(?<![.!?。！？])\b" + re.escape(word) + r"\b", re.UNICODE)
    return any(pattern.search(line.strip()) for line in text.splitlines())


_CJK_RUN_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]+")
# CJK characters that are grammar or deixis (pronouns, question words, copulas, particles,
# aspect markers). A shared bigram counts as content only when at least one of its
# characters is NOT in this set and not kana/hangul syllabic grammar, so "她问" / "他想" /
# "他们" / "什么" never anchor a pronoun-only question while "张伟", "飞机", "東京" do.
_CJK_GRAMMAR_CHARS = frozenset(
    "他她它们牠您我你咱俺們彼私僕俺君貴自身"
    "谁誰什么麼哪怎为為何如若是否的了吗嗎呢吧啊呀着著过過地得"
    "这這那些个個有没沒在和与與或但就都也很把被让讓对對于於从從到说說问問想要去来來做看给給用会會能可以及所因时時候里裡面上下前后後"
    "不无無非未再又还還只才已经經曾将將应該该應当當必须須"
    "请請告诉訴知道认觉覺记記听聽言"
    "之乎者也而其此彼焉然"
)
# Relative time/place words and pronoun compounds: 昨天 ("yesterday") / 自分 ("oneself") name nothing a reader could search for.
_CJK_DEIXIS_SPANS = frozenset(
    "昨天 今天 明天 前天 后天 後天 昨日 今日 明日 刚才 剛才 现在 現在 以前 以后 以後 之前 之后 之後 当时 當時 那时 那時 这时 這時 "
    "最近 后来 後來 去年 今年 明年 上周 下周 本周 上週 下週 本週 上月 下月 本月 早上 晚上 下午 上午 中午 今晚 昨晚 昨夜 今朝 "
    "这里 這裡 那里 那裡 这边 這邊 那边 那邊 "
    "自分 自身 自己 我们 我們 你们 你們 他们 他們 她们 她們 它们 它們 咱们 咱們 大家 各自 本人 彼女 彼ら 私達 私たち 我々 "
    "先週 来週 今週 先月 来月 今月 来年 昨年 一昨日 明後日 今朝 今夜 昨夜 午前 午後 最近 当時 以前 以後 ここ そこ あそこ".split()
)
_HIRAGANA_RE = re.compile(r"[぀-ゟ]")
# A hiragana run directly after a kanji/katakana character is okurigana + auxiliaries
# (言い+ました), never a content word; only runs that start a clause count.
_HIRAGANA_RUN_RE = re.compile(r"(?<![㐀-䶿一-鿿豈-﫿゠-ヿ])[぀-ゟ]+")
_HANGUL_RE = re.compile(r"[가-힯]")
# Hiragana grammar words (particles, copulas, auxiliaries, demonstratives, question words). A
# hiragana span is content only when it cannot be tiled by these, so さくら / ひこうき count
# while はどこ / あります / ですか do not.
_HIRAGANA_GRAMMAR_WORDS = frozenset(
    "は が を に で と の も へ や か な ね よ わ ぞ ぜ から まで より です ます でし まし ました ません ませ ない なく "
    "なかった ください くださ こと もの これ それ あれ どれ ここ そこ あそこ どこ なに なぜ いつ だれ どう どの この その あの "
    "いる ある する した して しま います あります あり いま いた いて いっ とき ため よう そう みたい など しか だけ ほど "
    "について において によって として でき できる できま のに ので けど でも また まだ もう ずっと とても すごく ちょっと "
    "ほとんど たち さん くん ちゃん なの のです んです でしょう だろう かしら っけ い し っ て た ん "
    "なん なんで なんの なんて どんな どうして どのように どれくらい いくつ いくら だれか なにか なにも だれも ほか もし "
    "ぜんぶ すべて いろいろ あなた わたし ぼく おれ かれ かのじょ かれら じぶん みんな きのう きょう あした あさって おととい "
    "いま さっき さきほど ことし きょねん らいねん こんしゅう せんしゅう らいしゅう こんげつ せんげつ らいげつ".split()
)
_HIRAGANA_MIN_SPAN = 2
# Korean is handled per word: strip trailing particles, then a stem of two or more syllables
# that is not grammar and occurs in the source is content.
_HANGUL_PARTICLES = (
    "에서", "으로", "에게", "한테", "부터", "까지", "께서", "이다", "입니다", "은", "는", "이", "가", "을", "를", "의", "에",
    "와", "과", "도", "로", "께", "만", "요",
)
_HANGUL_FUNCTION_WORDS = frozenset(
    "그 그녀 나 너 저 우리 당신 자신 자기 무엇 뭐 누구 어디 언제 어떻게 왜 어느 이것 그것 저것 무슨 어떤 몇 얼마 여기 거기 저기 "
    "했나요 합니까 입니까 있나요 없나요 했다 한다 있다 없다 했어요 해요 하나요 됩니까 되나요 그리고 그러나 하지만 또는 그래서 "
    "때문에 대해 대한 위해 통해 그런 이런 저런 있는 없는 하는 되는 된 한 할 될 그들 그는 그녀는 우리는 저는 나는 너는 "
    "어제 오늘 내일 모레 그제 지금 방금 아까 올해 작년 내년 이번 지난 다음 요즘 최근 당시 이전 이후 여기 거기 저기".split()
)
# Short function words of uncased scripts with whitespace (Arabic, Hebrew): never anchors.
_UNCASED_FUNCTION_WORDS = frozenset(
    {
        # three-letter grammar in Arabic/Hebrew (names such as علي / دبي are three letters too)
        "على", "إلى", "الى", "عن", "مع", "في", "من", "هل", "هذا", "هذه", "ذلك", "تلك", "كان", "قال", "لقد", "ثم",
        "لا", "ما", "لم", "لن", "كل", "أي", "اي", "هو", "هي", "هم", "هن", "أنا", "انا", "نحن", "أنت", "انت", "ليس",
        "بين", "حين", "أين", "فقط", "جدا", "ذات", "منذ", "نعم", "كلا", "عند", "لدى", "أجل",
        "הוא", "היא", "הם", "הן", "את", "של", "על", "אל", "עם", "מה", "מי", "כל", "גם", "רק", "לא", "כן", "אם",
        "או", "אז", "זה", "זו", "אלה", "היה", "היו", "יש", "אין", "כבר", "עוד", "שם", "פה", "כך", "מתי",
        "ماذا", "لماذا", "كيف", "متى", "اين", "هؤلاء", "أولئك", "الذي", "التي",
        "الذين", "اللاتي", "عندما", "كانوا", "كانت", "يكون", "قالوا", "قالت", "هناك", "هنا", "بعد", "قبل", "حول", "أيضا", "ايضا", "لكن", "حتى", "أيضًا", "ماهو", "ماهي", "وماذا", "ولماذا",
        "איפה", "למה", "איך", "האם", "הזה", "הזאת", "אלו", "אמר", "אמרה", "אמרו", "היתה", "הייתה", "כאשר", "אשר", "אבל", "לפני", "אחרי", "אצל", "מדוע", "כיצד", "היכן", "מהו", "מהי",
    }
)
_UNCASED_WORD_MIN_LETTERS = 3


def _is_content_ideograph(ch: str) -> bool:
    return bool(ch) and has_cjk(ch) and ch not in _CJK_GRAMMAR_CHARS and not _HIRAGANA_RE.match(ch) and not _HANGUL_RE.match(ch)


def _is_cjk_deixis(run: str, index: int, excerpt_norm: str | None = None) -> bool:
    """True when the bigram at `index` lies inside a relative time/place word (昨天, 先週) that
    stands on its own; a deictic span embedded in a longer compound the source also carries
    (明日香, Asuka) is part of a name, not deixis."""
    for width in (2, 3):
        for start in range(max(0, index - width + 1), index + 2):  # any word overlapping either character
            span = run[start : start + width]
            if span not in _CJK_DEIXIS_SPANS:
                continue
            if excerpt_norm is not None:
                before = run[start - 1] if start > 0 else ""
                after = run[start + width] if start + width < len(run) else ""
                # only a content ideograph can extend a deictic span into a name (明日+香, not 他+昨天)
                before = before if _is_content_ideograph(before) else ""
                after = after if _is_content_ideograph(after) else ""
                for compound in (before + span, span + after, before + span + after):
                    if len(compound) > width and compound in excerpt_norm:
                        return False
            return True
    return False


_JA_NOUN_PARTICLES = frozenset("はがをにでへのもと")


def _single_kanji_noun(question_norm: str, excerpt_norm: str) -> bool:
    """A lone kanji/hanzi directly followed by a case particle is a noun (犬は, 本を), unlike a
    kanji followed by okurigana (食べ); it anchors when the source contains it."""
    for i, ch in enumerate(question_norm[:-1]):
        if ch in _CJK_GRAMMAR_CHARS or not has_cjk(ch) or _HIRAGANA_RE.match(ch) or _HANGUL_RE.match(ch):
            continue
        if question_norm[i + 1] not in _JA_NOUN_PARTICLES:
            continue
        if i > 0 and has_cjk(question_norm[i - 1]) and not _HIRAGANA_RE.match(question_norm[i - 1]):
            continue  # part of a longer compound, handled by the bigram rule
        if ch in excerpt_norm:
            return True
    return False


def _is_cjk_content_span(span: str) -> bool:
    """Both characters must be kanji/hanzi/katakana (a kanji next to a particle or okurigana —
    を食, 言い — is a predicate stem) and at least one must not be grammar/deixis, so 上野 is a
    name while 他们 / 什么 are not. Hiragana and hangul have their own word-level rules."""
    if any(_HIRAGANA_RE.match(ch) or _HANGUL_RE.match(ch) for ch in span):
        return False
    return any(ch not in _CJK_GRAMMAR_CHARS for ch in span)


_HIRAGANA_SINGLE_GRAMMAR = frozenset(w for w in _HIRAGANA_GRAMMAR_WORDS if len(w) == 1)
_HIRAGANA_MULTI_GRAMMAR = frozenset(w for w in _HIRAGANA_GRAMMAR_WORDS if len(w) >= 2)


def _segment_hiragana(run: str) -> list[bool]:
    """Per-character grammar mask for a hiragana run.

    Dynamic programme minimising the number of uncovered characters where multi-character
    grammar words (です, から, ました) tile freely and a single-character particle (は, を, か)
    may only attach where a particle can stand — right after grammar / the run start, or
    right before a multi-character grammar word / the run end. That keeps particles from
    fragmenting a noun (さかな is never さ+か+な) while それ|は|なん|です|か tiles completely.
    """
    n = len(run)
    unreachable = 10**9
    # state: (position, previous token was grammar-or-boundary) -> (uncovered, mask)
    best: dict[tuple[int, bool], tuple[int, tuple[bool, ...]]] = {(0, True): (0, ())}
    for i in range(n):
        for prev_grammar in (True, False):
            state = best.get((i, prev_grammar))
            if state is None:
                continue
            cost, mask = state
            # uncovered character
            cand = (cost + 1, mask + (False,))
            key = (i + 1, False)
            if cand[0] < best.get(key, (unreachable, ()))[0]:
                best[key] = cand
            # multi-character grammar word
            for j in range(i + 2, min(n, i + 6) + 1):
                if run[i:j] in _HIRAGANA_MULTI_GRAMMAR:
                    cand = (cost, mask + (True,) * (j - i))
                    key = (j, True)
                    if cand[0] < best.get(key, (unreachable, ()))[0]:
                        best[key] = cand
            # single-character particle
            if run[i] in _HIRAGANA_SINGLE_GRAMMAR:
                next_is_boundary = i + 1 == n or any(run[i + 1 : i + 1 + w] in _HIRAGANA_MULTI_GRAMMAR for w in range(2, 7))
                if prev_grammar or next_is_boundary:
                    cand = (cost, mask + (True,))
                    key = (i + 1, True)
                    if cand[0] < best.get(key, (unreachable, ()))[0]:
                        best[key] = cand
    finals = [best[k] for k in ((n, True), (n, False)) if k in best]
    _cost, mask = min(finals, key=lambda item: item[0])
    return list(mask)


def _hiragana_words(run: str) -> list[str]:
    """The uncovered chunks of a hiragana run: the word candidates (さかな in さかなはどこにいますか)."""
    words: list[str] = []
    current = ""
    for ch, is_grammar in zip(run, _segment_hiragana(run), strict=True):
        if is_grammar:
            if current:
                words.append(current)
            current = ""
        else:
            current += ch
    if current:
        words.append(current)
    return words


def _hiragana_content_span(question_norm: str, excerpt_norm: str) -> bool:
    for run in _HIRAGANA_RUN_RE.findall(question_norm):
        for word in _hiragana_words(run):
            if len(word) >= _HIRAGANA_MIN_SPAN and word in excerpt_norm:
                return True
    return False


_HANGUL_PREDICATE_ENDINGS = (
    "습니까", "습니다", "ㅂ니까", "했나요", "었나요", "았나요", "였나요", "했어요", "었어요", "았어요", "했다", "었다", "았다",
    "였다", "인가요", "한가요", "할까요", "됐나요", "되나요", "하나요", "있나요", "없나요", "나요", "어요", "아요", "이다",
    "니까", "니다", "는가", "은가", "ㄹ까",
)


def _hangul_stem(word: str) -> str:
    """Strip one trailing case particle (the longest that matches), never below two syllables:
    회의는 -> 회의, 서울에서 -> 서울; the 의 of 회의 is lexical and stays."""
    for particle in sorted(_HANGUL_PARTICLES, key=len, reverse=True):
        if word.endswith(particle) and len(word) - len(particle) >= 2:
            return word[: -len(particle)]
    return word


def _is_hangul_predicate(word: str) -> bool:
    return any(word.endswith(ending) for ending in _HANGUL_PREDICATE_ENDINGS)


def _hangul_content_word(question_norm: str, excerpt_norm: str) -> bool:
    for word in tokens(question_norm):
        if not _HANGUL_RE.search(word) or any(ch.isdigit() for ch in word):
            continue
        if word in _HANGUL_FUNCTION_WORDS or _is_hangul_predicate(word):
            continue
        stem = _hangul_stem(word)
        if len(stem) < 2 or stem in _HANGUL_FUNCTION_WORDS:
            continue
        if stem in excerpt_norm:
            return True
    return False


_HEBREW_CLITICS = "והבלמשכ"
_ARABIC_CLITICS = "وفبلكس"


def _semitic_forms(token: str) -> set[str]:
    """The token and its clitic-stripped forms (Hebrew ו/ה/ב/ל/מ/ש/כ, Arabic و/ف/ب/ل/ك/س and ال)."""
    forms = {token}
    current = token
    for _ in range(2):
        if current and (current[0] in _HEBREW_CLITICS or current[0] in _ARABIC_CLITICS) and len(current) > 2:
            current = current[1:]
            forms.add(current)
    for form in list(forms):
        if form.startswith("ال") and len(form) > 3:
            forms.add(form[2:])
    return forms


def _is_uncased_function_word(token: str) -> bool:
    return any(form in _UNCASED_FUNCTION_WORDS for form in _semitic_forms(token))


def _shares_content_span(question: str, source_excerpt: str) -> bool:
    """Uncased scripts cannot single out a name by capitalization, so the anchor is a content span
    the question shares with the source it was generated from: a CJK bigram that is not grammar,
    or a whole word of at least four uncased letters that is not a function word."""
    excerpt_norm = normalize_text(source_excerpt)
    if not excerpt_norm:
        return False
    question_norm = normalize_text(question)  # NFKC on both sides (full-width forms)
    for run in _CJK_RUN_RE.findall(question_norm):
        for i in range(len(run) - 1):
            span = run[i : i + 2]
            if _is_cjk_deixis(run, i, excerpt_norm) or not _is_cjk_content_span(span):
                continue
            if span in excerpt_norm:
                return True
    if _single_kanji_noun(question_norm, excerpt_norm):
        return True
    if _hiragana_content_span(question_norm, excerpt_norm) or _hangul_content_word(question_norm, excerpt_norm):
        return True
    excerpt_forms: set[str] = set()
    for token in tokens(source_excerpt):
        excerpt_forms.update(_semitic_forms(token))
    for token in tokens(question):
        if has_cjk(token) or any(ch.isdigit() for ch in token):
            continue  # numbers are the number rule's business
        if any(ch.isalpha() and ch.upper() != ch.lower() for ch in token):
            continue  # cased scripts are handled by _has_anchor
        if _is_uncased_function_word(token):
            continue
        for form in _semitic_forms(token):
            if len(form) >= _UNCASED_WORD_MIN_LETTERS and form in excerpt_forms and not _is_uncased_function_word(form):
                return True
    return False


_MIN_WORDS = 4
_GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")


def _ends_with_question_mark(text: str) -> bool:
    """``?``, full-width ``？``, Arabic ``؟``; Greek writes its question mark as ``;`` (or U+037E)."""
    if text.endswith(("?", "？", "؟")):
        return True
    return text.endswith((";", "\u037e")) and _GREEK_RE.search(text) is not None


def is_self_contained_question(question: str, *, source_excerpt: str | None = None) -> bool:
    """Ends with a question mark, is long enough, never refers to the source, and carries an anchor.

    Length is counted with the shared Unicode tokenizer (CJK runs count per character
    because they carry no word boundaries). Anchors are numbers, quoted phrases,
    addresses, or a capitalized non-initial word in any cased script. Questions in
    uncased scripts (CJK, Arabic, Hebrew, ...) are anchored only by a content span they
    share with ``source_excerpt`` (the text they were generated from); without an
    excerpt such a question has no provable anchor and is rejected. Self-references
    are matched against an explicit multilingual list; the judge is the second line.
    """
    text = str(question or "").strip()
    if not _ends_with_question_mark(text):
        return False
    cjk_chars = sum(1 for ch in text if has_cjk(ch))
    word_count = max(len(tokens(text)), cjk_chars)
    if word_count < _MIN_WORDS:
        return False
    excerpt = str(source_excerpt) if source_excerpt else None
    if _SELF_REFERENCE_RE.search(text) is not None and not _identified_by_title(text, excerpt):
        return False
    if _has_pronominal_subject(text):
        return False  # "What did he say about Barry Cohen?": no anchor can say who "he" is
    if _has_anchor(text, excerpt):
        return True
    return bool(excerpt) and _shares_content_span(text, excerpt)


def judge_accepts(*, score: float, keep: bool, threshold: float) -> bool:
    """The configured curation threshold is authoritative; the prompt's keep flag is advisory only."""
    del keep
    return float(score) >= float(threshold)


def _reject_json_constant(name: str) -> float:
    raise ValueError(f"non-finite JSON constant {name!r}")


def parse_judge_verdict(text: str) -> tuple[float, bool, str]:
    try:
        payload = json.loads(_extract_json(text, opener="{", closer="}"), parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise GroundedQAParseError(f"judge output is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise GroundedQAParseError("judge output is not a JSON object")
    raw_score = payload.get("score")
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
        raise GroundedQAParseError("judge output has no numeric score")
    try:
        score_value = float(raw_score)  # a huge JSON integer overflows here rather than at the clamp
    except (OverflowError, ValueError) as exc:
        raise GroundedQAParseError(f"judge score is not representable: {exc}") from exc
    if not math.isfinite(score_value):
        raise GroundedQAParseError("judge output has no finite numeric score")
    score = min(10.0, max(0.0, score_value))
    raw_keep = payload.get("keep")
    keep = bool(raw_keep) if isinstance(raw_keep, bool) else score >= 7.0
    reason = str(payload.get("reason") or "").strip()
    return score, keep, reason


def source_excerpt(content: str, *, max_lines: int) -> str:
    lines = str(content or "").splitlines()
    return "\n".join(lines[: max(1, int(max_lines))]).strip()


def build_eval_item(
    row: dict[str, Any],
    *,
    source_path: str,
    source_kind: str,
    include_expected_answer: bool,
    include_tags: bool,
    limits: SyntheticGeneratorConfig,
) -> EvalDatasetItem | None:
    question = str(row.get("question") or "").strip()
    answer = str(row.get("expected_answer") or "").strip()
    quote = str(row.get("evidence_quote") or "").strip()
    if not question or len(question) > int(limits.question_max_chars):
        return None
    if not answer or len(answer) > int(limits.expected_answer_max_chars):
        return None
    if not quote or len(quote) > int(limits.evidence_quote_max_chars):
        return None
    del include_expected_answer  # the generated answer stays on the row until publication (see publish_item)
    tags: list[str] = []
    if include_tags:
        tags = ["synthetic", PROVIDER_NAME]
        if source_kind:
            tags.append(source_kind)
    return EvalDatasetItem(
        question=question,
        expected_paths=[source_path],
        expected_answer=answer,
        evidence_quote=quote,
        tags=tags,
    )


def publish_item(item: EvalDatasetItem, *, include_expected_answer: bool) -> EvalDatasetItem:
    """The published row omits the answer only when the operator asked for retrieval-only rows."""
    if include_expected_answer:
        return item
    return item.model_copy(update={"expected_answer": ""})


def _render_prompt(template: str, values: dict[str, Any]) -> str:
    rendered = str(template or "")
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def is_local_serving_alias(alias: str) -> bool:
    row = gateway_rows_snapshot().get(alias)
    return row is not None and row.provider == LOCAL_SERVING_PROVIDER


def gateway_concurrency(cfg: TriBridConfig, *aliases: str) -> int:
    """Configured generator concurrency, forced to one stream for the local vLLM alias."""
    limit = max(1, int(cfg.synthetic.generator.concurrency))
    if any(is_local_serving_alias(alias) for alias in aliases):
        return 1
    return limit


def _alias_semaphore(alias: str, *, run_semaphore: asyncio.Semaphore) -> asyncio.Semaphore:
    """The local serving alias is single-stream for the whole process; other aliases use the run's limit."""
    if is_local_serving_alias(alias):
        semaphore = _LOCAL_ALIAS_SEMAPHORES.get(alias)
        if semaphore is None:
            semaphore = asyncio.Semaphore(1)
            _LOCAL_ALIAS_SEMAPHORES[alias] = semaphore
        return semaphore
    return run_semaphore


async def _cancellable(coro: Coroutine[Any, Any, T], cancel_event: asyncio.Event | None) -> T:
    """Await ``coro`` but abort it the moment ``cancel_event`` fires (no orphaned paid calls)."""
    if cancel_event is None:
        return await coro
    if cancel_event.is_set():
        coro.close()
        raise asyncio.CancelledError()
    task = asyncio.ensure_future(coro)
    waiter = asyncio.ensure_future(cancel_event.wait())
    try:
        done, _pending = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            return task.result()
        raise asyncio.CancelledError()
    except BaseException:
        # The cancel event fired, a sibling failed and the TaskGroup cancelled us, or
        # the caller was cancelled: the paid gateway call must not keep running.
        if not task.done():
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
        raise
    finally:
        waiter.cancel()


@dataclass
class _Stats:
    generated: int = 0
    rejected_malformed: int = 0
    rejected_ungrounded: int = 0
    judged: int = 0
    kept: int = 0
    judge_scores: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class _Candidate:
    item: EvalDatasetItem
    source_path: str
    source_excerpt: str


async def _generate_rows_for_chunk(
    *,
    cfg: TriBridConfig,
    route: ProviderRoute,
    chunk: Chunk,
    num_pairs: int,
    request: SyntheticRunStartRequest,
    timeout_s: float,
    stats: _Stats,
    cancel_event: asyncio.Event | None,
) -> list[_Candidate]:
    generator_cfg = cfg.synthetic.generator
    excerpt = source_excerpt(str(chunk.content or ""), max_lines=int(generator_cfg.source_excerpt_max_lines))
    file_path = str(chunk.file_path or "").strip()
    if not excerpt or not file_path:
        return []
    system_prompt = _render_prompt(
        cfg.system_prompts.synthetic_generator,
        {
            "num_pairs": num_pairs,
            "question_max_chars": generator_cfg.question_max_chars,
            "expected_answer_max_chars": generator_cfg.expected_answer_max_chars,
            "evidence_quote_max_chars": generator_cfg.evidence_quote_max_chars,
        },
    )
    user_message = f"source_file_path: {file_path}\nsource_excerpt:\n{excerpt}"
    try:
        result = await _cancellable(
            generate_chat_text(
                route=route,
                system_prompt=system_prompt,
                user_message=user_message,
                images=[],
                image_detail="auto",
                temperature=float(generator_cfg.temperature),
                max_tokens=int(generator_cfg.max_tokens),
                context_text="",
                context_chunks=[],
                timeout_s=timeout_s,
            ),
            cancel_event,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise GroundedQAGenerationError(f"generator alias {route.model!r} failed for {file_path}: {exc}") from exc

    try:
        rows = parse_generated_rows(str(result.text or ""))
    except GroundedQAParseError:
        stats.rejected_malformed += 1
        return []

    source_kind = _infer_source_kind(file_path, excerpt)
    candidates: list[_Candidate] = []
    for row in rows[:num_pairs]:
        stats.generated += 1
        item = build_eval_item(
            row,
            source_path=file_path,
            source_kind=source_kind,
            include_expected_answer=bool(request.include_expected_answer),
            include_tags=bool(request.include_tags),
            limits=generator_cfg,
        )
        if item is None or not is_self_contained_question(item.question, source_excerpt=excerpt):
            stats.rejected_malformed += 1
            continue
        if not is_grounded(item.evidence_quote, excerpt) or not answer_is_anchored(item.expected_answer, excerpt):
            stats.rejected_ungrounded += 1
            continue
        candidates.append(_Candidate(item=item, source_path=file_path, source_excerpt=excerpt))
    return candidates


async def _judge_candidate(
    *,
    cfg: TriBridConfig,
    route: ProviderRoute,
    candidate: _Candidate,
    threshold: float,
    timeout_s: float,
    stats: _Stats,
    cancel_event: asyncio.Event | None,
) -> bool:
    judge_cfg = cfg.synthetic.judge
    payload = {
        "question": candidate.item.question,
        "expected_paths": candidate.item.expected_paths,
        "expected_answer": candidate.item.expected_answer or "",
        "evidence_quote": candidate.item.evidence_quote or "",
        "source_file_path": candidate.source_path,
        "source_excerpt": candidate.source_excerpt,
    }
    try:
        result = await _cancellable(
            generate_chat_text(
                route=route,
                system_prompt=cfg.system_prompts.synthetic_judge,
                user_message=json.dumps(payload, ensure_ascii=False, indent=2),
                images=[],
                image_detail="auto",
                temperature=float(judge_cfg.temperature),
                max_tokens=int(judge_cfg.max_tokens),
                context_text="",
                context_chunks=[],
                timeout_s=timeout_s,
            ),
            cancel_event,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise GroundedQAGenerationError(f"judge alias {route.model!r} failed: {exc}") from exc
    try:
        score, keep, _reason = parse_judge_verdict(str(result.text or ""))
    except GroundedQAParseError:
        stats.rejected_malformed += 1
        return False
    stats.judged += 1
    stats.judge_scores.append(score)
    return judge_accepts(score=score, keep=keep, threshold=threshold)


async def generate_eval_items(
    *,
    cfg: TriBridConfig,
    request: SyntheticRunStartRequest,
    chunks: list[Chunk],
    cancel_event: asyncio.Event | None,
    on_progress: ProgressCallback | None,
) -> tuple[list[EvalDatasetItem], _Stats]:
    curate = bool(request.curate_enabled)
    generator_route = resolve_synthetic_route(cfg=cfg, model=str(request.generator_model or ""))
    judge_route = resolve_synthetic_route(cfg=cfg, model=str(request.judge_model or "")) if curate else None
    aliases = [generator_route.model] + ([judge_route.model] if judge_route is not None else [])
    concurrency = gateway_concurrency(cfg, *aliases)
    timeout_s = float(cfg.generation.gen_timeout)
    max_pairs = max(1, int(request.max_pairs or 150))
    pairs_per_source = max(1, int(request.pairs_per_source or 1))
    threshold = float(request.curate_threshold)
    stats = _Stats()
    kept: list[EvalDatasetItem] = []
    run_semaphore = asyncio.Semaphore(concurrency)
    generator_semaphore = _alias_semaphore(generator_route.model, run_semaphore=run_semaphore)
    judge_semaphore = (
        _alias_semaphore(judge_route.model, run_semaphore=run_semaphore) if judge_route is not None else run_semaphore
    )

    def _check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError()

    async def _process(chunk: Chunk) -> list[EvalDatasetItem]:
        _check_cancelled()
        async with generator_semaphore:
            candidates = await _generate_rows_for_chunk(
                cfg=cfg,
                route=generator_route,
                chunk=chunk,
                num_pairs=pairs_per_source,
                request=request,
                timeout_s=timeout_s,
                stats=stats,
                cancel_event=cancel_event,
            )
        items: list[EvalDatasetItem] = []
        for candidate in candidates:
            if judge_route is not None:
                _check_cancelled()
                async with judge_semaphore:
                    accepted = await _judge_candidate(
                        cfg=cfg,
                        route=judge_route,
                        candidate=candidate,
                        threshold=threshold,
                        timeout_s=timeout_s,
                        stats=stats,
                        cancel_event=cancel_event,
                    )
                if not accepted:
                    continue
            items.append(candidate.item)
        return items

    if on_progress is not None:
        await on_progress(
            f"Generating grounded QA rows with {generator_route.model} "
            f"(judge {judge_route.model if judge_route is not None else 'disabled'}, concurrency {concurrency}) "
            f"over {len(chunks)} source chunks.",
            0.0,
        )

    for start in range(0, len(chunks), concurrency):
        _check_cancelled()
        batch = chunks[start : start + concurrency]
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(_process(chunk)) for chunk in batch]
        for task in tasks:
            kept.extend(task.result())
        stats.kept = len(kept)
        if on_progress is not None:
            done = min(len(chunks), start + len(batch))
            await on_progress(
                f"{done}/{len(chunks)} sources processed: {stats.generated} generated, "
                f"{stats.rejected_ungrounded} ungrounded, {stats.rejected_malformed} malformed, {len(kept)} kept.",
                100.0 * done / max(1, len(chunks)),
            )
        if len(kept) >= max_pairs:
            break
    return kept[:max_pairs], stats


async def run_grounded_qa_provider(
    *,
    run_id: str,
    repo_id: str,
    cfg: TriBridConfig,
    request: SyntheticRunStartRequest,
    cancel_event: asyncio.Event | None = None,
    on_progress: ProgressCallback | None = None,
) -> tuple[dict[SyntheticArtifactKind, Any], SyntheticRunSummary, list[EvalDatasetItem]]:
    """Return artifacts (eval rows already published), the run summary, and the unpublished rows
    (answers intact) for the quality gate and trace mining."""
    _ = run_id
    chunks = await select_source_chunks(repo_id=repo_id, cfg=cfg, request=request)
    if not chunks:
        raise GroundedQAGenerationError(
            f"No indexed source chunks found for corpus {repo_id!r}; index the corpus before generating eval rows."
        )

    eval_items: list[EvalDatasetItem] = []
    stats = _Stats()
    if request.recipe in EVAL_RECIPES:
        eval_items, stats = await generate_eval_items(
            cfg=cfg,
            request=request,
            chunks=chunks,
            cancel_event=cancel_event,
            on_progress=on_progress,
        )

    summaries = [_chunk_to_summary(ch, card_source="deterministic") for ch in chunks]
    keywords = _derive_keywords(summaries, max_keywords=int(cfg.keywords.keywords_max_per_repo or 80))
    patch = _autotune_patch(cfg=cfg, eval_items=eval_items, keywords=keywords)

    artifacts: dict[SyntheticArtifactKind, Any] = {}
    if request.recipe in {"semantic_cards", "full_stack"}:
        artifacts["semantic_cards_jsonl"] = summaries
    if request.recipe in EVAL_RECIPES:
        include_answer = bool(request.include_expected_answer)
        artifacts["eval_dataset_json"] = [publish_item(item, include_expected_answer=include_answer) for item in eval_items]
    if request.recipe in {"keywords", "full_stack"}:
        artifacts["keywords_json"] = keywords
    if request.recipe in {"autotune_retrieval", "full_stack"}:
        artifacts["config_patch_json"] = patch

    curate = bool(request.curate_enabled)
    avg_judge_score = (sum(stats.judge_scores) / len(stats.judge_scores)) if stats.judge_scores else None
    artifacts["report_md"] = (
        "Grounded QA rows generated through the LiteLLM gateway with verbatim evidence checks.\n"
        f"Generator model: {request.generator_model}\n"
        f"Judge model: {request.judge_model if curate else '(curation disabled)'}\n"
        f"Sources used: {len(chunks)}\n"
        f"Rows generated: {stats.generated}\n"
        f"Rejected (ungrounded quote or unanchored answer): {stats.rejected_ungrounded}\n"
        f"Rejected (malformed / self-referential / over limit): {stats.rejected_malformed}\n"
        f"Judged: {stats.judged}\n"
        f"Eval items kept: {len(eval_items)}\n"
        f"Keywords: {len(keywords)}\n"
    )

    summary = SyntheticRunSummary()
    summary.sources_used = len(chunks)
    summary.items_generated = stats.generated
    summary.items_rejected_ungrounded = stats.rejected_ungrounded
    summary.items_rejected_malformed = stats.rejected_malformed
    summary.items_curated_in = stats.judged if curate else 0
    summary.items_curated_out = len(eval_items)
    summary.avg_judge_score = avg_judge_score
    return artifacts, summary, eval_items
