from __future__ import annotations

import re

import pytest

from server.evaluation.query_guard import is_real_query
from server.models.index import Chunk, ChunkProvenance, PageRegion
from server.models.tribrid_config_model import (
    EvalDatasetItem,
    EvalExpectedLocation,
    SyntheticGeneratorConfig,
    SyntheticJudgeConfig,
)
from server.synthetic.providers.grounded_qa_provider import (
    ANSWER_CUED,
    ANSWER_SUPPORTED,
    JUDGE_QUESTIONS,
    READER_QUESTION,
    GroundedQAParseError,
    JudgeVerdict,
    answer_is_anchored,
    build_eval_item,
    is_grounded,
    is_self_contained_question,
    judge_accepts,
    judge_state,
    judge_verdict,
    parse_generated_rows,
    source_excerpt,
    source_location,
)

EMAIL = (
    "Thinking of switching from Jet Aviation to EJM. EJM is more expensive. Do you have a point of view?\n"
    "\n"
    'Email metadata: Barry J. Cohen emailed Jeffrey Epstein on 2017-10-02 14:33:00. Subject: "Plane management".\n'
)
EMAIL_PATH = "HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt"
EMAIL_LOCATION = EvalExpectedLocation(path=EMAIL_PATH, unit="line", start=1, end=3)


def test_parse_generated_rows_accepts_a_bare_json_array() -> None:
    rows = parse_generated_rows(
        '[{"question": "Which plane management company did Barry Cohen consider switching to from Jet Aviation?",'
        ' "expected_answer": "EJM", "evidence_quote": "switching from Jet Aviation to EJM"}]'
    )
    assert len(rows) == 1
    assert rows[0]["expected_answer"] == "EJM"


def test_parse_generated_rows_accepts_fenced_json_and_rows_object() -> None:
    fenced = (
        "```json\n"
        '{"rows": [{"question": "Who emailed Jeffrey Epstein about plane management on 2017-10-02?",'
        ' "expected_answer": "Barry J. Cohen", "evidence_quote": "Barry J. Cohen emailed Jeffrey Epstein"}]}\n'
        "```"
    )
    rows = parse_generated_rows(fenced)
    assert [r["expected_answer"] for r in rows] == ["Barry J. Cohen"]


def test_parse_generated_rows_rejects_prose_and_non_object_rows() -> None:
    with pytest.raises(GroundedQAParseError):
        parse_generated_rows("Here are some questions about the email.")
    with pytest.raises(GroundedQAParseError):
        parse_generated_rows('["just a string"]')


def test_is_grounded_requires_a_verbatim_quote_modulo_whitespace_and_quotes() -> None:
    assert is_grounded("switching from Jet Aviation  to EJM", EMAIL)
    assert is_grounded("subject: “plane management”", EMAIL)
    assert not is_grounded("Cohen wanted to move to EJM because it was cheaper", EMAIL)
    assert not is_grounded("", EMAIL)


def test_self_contained_question_rejects_references_to_the_source_itself() -> None:
    assert is_self_contained_question(
        "Which plane management company did Barry Cohen consider switching to from Jet Aviation in October 2017?"
    )
    assert not is_self_contained_question("What does this email say about EJM?")
    assert not is_self_contained_question("Who is the sender of the message above?")
    assert not is_self_contained_question("According to the excerpt, who wrote to Epstein?")
    assert not is_self_contained_question("Jet Aviation vs EJM")
    # pronoun-only questions carry no anchor a reader could search for
    assert not is_self_contained_question("What did he recommend?")
    assert not is_self_contained_question("Where did they say they needed to meet?")
    assert not is_self_contained_question("What did He say about It?")
    assert is_self_contained_question("Who asked Jeffrey Epstein whether he could speak now on 2016-11-12?")
    assert is_self_contained_question("Who described the buoy array as 'drifting beyond tolerance' in the log?")
    assert is_self_contained_question("Where did anasalrasheed@gmail.com say they needed to see Epstein?")
    # CJK questions: no whitespace words or capitalization; length in characters, digits anchor,
    # otherwise a content span shared with the source excerpt (see the uncased-script matrix)
    assert is_self_contained_question("张伟在2017年10月发送了哪封关于飞机管理的邮件？")
    assert not is_self_contained_question("他说了什么？")


@pytest.mark.parametrize(
    "question",
    [
        # the same question shape in cased scripts: a capitalized non-initial name anchors it
        "Who asked Jeffrey Epstein to call Barry Cohen in October 2017?",
        "Кто попросил Джеффри Эпштейна позвонить Барри Коэну?",
        "Ποιος ζήτησε από τον Τζέφρι Έπσταϊν να καλέσει τον Μπάρι Κοέν;",
        "Quelle société de gestion d'avions Émile Zola a-t-il recommandée à Épstein ?",
        "Wer bat Jeffrey Epstein, Barry Cohen im Oktober anzurufen?",
        "Какая температура была выше 30 градусов на буе Aurora в марте?",  # "выше" = "higher than", not "above"
        # addresses and numbers anchor in any script, including digits inside a CJK run
        "Who contacted anasalrasheed@gmail.com about arrangements yesterday?",
        "张伟在2017年10月发送了哪封关于飞机管理的邮件？",
    ],
)
def test_self_contained_guard_is_script_independent(question: str) -> None:
    # Codex pass 5/6: the anchor regex was [A-Z]-only, length used str.split(), lowercase e-mails
    # were dropped by the capitalization check and \b never fired between CJK and digits.
    assert is_real_query(question)
    assert is_self_contained_question(question)


@pytest.mark.parametrize(
    ("question", "excerpt"),
    [
        # uncased scripts: the anchor is a content span shared with the source the question came from
        ("من طلب من جيفري إبستين الاتصال بباري كوهين في أكتوبر؟", "كتب جيفري إبستين إلى باري كوهين في أكتوبر بشأن إدارة الطائرة"),
        ("מי ביקש מג'פרי אפשטיין להתקשר לבארי כהן באוקטובר?", "ג'פרי אפשטיין ביקש מבארי כהן להתקשר באוקטובר"),
        ("発信者はなぜ機体管理会社をジェットアビエーションから変更したのですか？", "発信者は機体管理会社をジェットアビエーションからEJMに変更した。"),
        ("東京はどこ？", "観測所は東京の南にある。"),
        ("发件人为什么考虑把飞机管理从捷特航空换到另一家公司？", "发件人考虑把飞机管理从捷特航空换到EJM。"),
        ("من رأى علي في دبي؟", "رأى أحمد علي في دبي أمس"),  # three-letter names (codex pass 7)
        # codex pass 8: all-hiragana content words, Korean stems, clitic-prefixed names
        ("さくらはどこにありますか？", "にわにさくらがあります。"),
        ("ひこうきはいつとびましたか？", "ひこうきはきのうとびました。"),
        ("さかなはどこにいますか？", "水槽にさかながいる。"),  # codex pass 9: さ+かな must not tile a noun
        ("서울에서 누가 장비를 보정했나요?", "서울에서 김민수가 장비를 보정했다."),
        ("회의는 언제 시작했나요?", "회의 일정은 오후 세 시다."),  # codex pass 9: the 의 of 회의 is lexical
        ("犬はどこですか？", "犬は庭にいます。"),  # codex pass 10: a lone kanji before a case particle is a noun
        ("猫は何を食べましたか？", "猫は魚を食べました。"),
        ("من طلب من جيفري إبستين الاتصال بباري كوهين في أكتوبر؟", "كتب جيفري إبستين إلى باري كوهين في أكتوبر"),
    ],
)
def test_uncased_script_questions_anchor_on_a_content_span_shared_with_the_source(question: str, excerpt: str) -> None:
    assert is_real_query(question)
    assert is_self_contained_question(question, source_excerpt=excerpt)
    # without the source there is no provable anchor (letter count is not anchoring)
    assert not is_self_contained_question(question)


@pytest.mark.parametrize(
    ("question", "excerpt"),
    [
        ("Что он сказал об этом?", None),  # pronoun-only, Cyrillic: no name, number or quote
        ("Was hat er dazu gesagt?", None),
        ("ماذا قال؟", None),  # too short
        ("ماذا قالوا عندما كانوا هناك؟", "قالوا عندما كانوا هناك إن الجهاز معطل"),  # pronoun-only even though the words recur
        ("他说了什么？", "他说了什么都不重要"),
        # codex pass 7: pronoun + verb bigrams are grammar, not content, even when the source repeats them
        ("她问了什么？", "她问了什么都不重要"),
        ("他想要什么？", "他想要什么呢"),
        ("他们去了哪里？", "他们去了哪里我不知道"),
        # deictic source references beyond "this email"
        ("What does the attached email say about EJM?", None),
        ("What did the following document say about Barry Cohen?", None),
        ("According to the attachment, who called Barry Cohen?", None),
        # a quoted pronoun is not an anchor; a quoted phrase absent from the source is not either
        ("What did he say about 'it'?", None),
        ("Who described the buoy array as 'drifting beyond tolerance' in the log?", "The log says nothing like that."),
        # a sentence-initial capitalized verb is not a name even when the source repeats it
        ("Calibrate the sensor array now?", "Calibrate the sensor array every 45 days. We calibrate weekly."),
        ("Aurora recorded what salinity after calibration?", None),  # no source: the initial word is unprovable
        # codex pass 8: pronoun/question-only questions in ja/ko/he even against the same sentence,
        # and bare "the email says" discourse references
        ("彼は何を言いましたか？", "彼は何を言いましたか"),
        ("彼は何を食べましたか？", "彼は何を食べましたか"),  # codex pass 9: lone kanji + okurigana is a predicate
        ("それはなんですか？", "それはなんですか"),
        ("あなたはだれですか？", "あなたはだれですか"),
        ("かれはなにをいいましたか？", "かれはなにをいいました"),
        ("그는 무엇을 했나요?", "그는 무엇을 했나요 모른다"),
        ("그는 무엇을 썼나요?", "그는 무엇을 썼나요 모른다"),  # codex pass 9: predicate morphology
        ("ומה הוא אמר שם?", "ומה הוא אמר שם לא ידוע"),
        # codex pass 19: the cleft exemption applies to the expletive `it` only, not an earlier `it`
        ("Did it matter — was it Barry Cohen who called in October 2017?", "Barry Cohen called in October 2017."),
        # codex pass 18: "Was it X?" has no cleft clause; an unresolved `it` stays rejected
        ("Was it Barry Cohen?", None),
        # codex pass 17: a verb form is never an antecedent; an inanimate head noun does not bind
        ("What happened to their aircraft in October 2017?", "Their aircraft was grounded in October 2017."),
        # codex pass 16: a nominative pronoun after a reporting verb is an embedded subject; possessives are
        # type-aware (his needs a person) and every one is checked
        ("Which witness statement said he called Barry Cohen in October 2017?", "The statement said he called Barry Cohen."),
        ("Which companies changed their policies after his arrest in October 2017?", "Companies changed their policies after his arrest."),
        # codex pass 15: an unresolved subject pronoun or possessive rejects the row even when another
        # entity appears ("What did he say about Barry Cohen?"); a named antecedent resolves it
        ("What was his account balance at EJM?", "His account balance at EJM was 40,000."),
        ("他的名字是什么？", "他的名字是张伟。"),
        ("What did he say about Barry Cohen?", None),
        ("What did he write about his plane in October 2017?", None),
        ("他昨天去了北京吗？", "他昨天去了北京。"),
        # codex pass 14: a pronoun after the clause auxiliary is the subject wherever it sits; a title
        # on another noun does not identify "the excerpt"; more Portuguese interrogatives
        ("Which of the 2017 regulations did he enforce?", "He enforced the 2017 regulations."),
        ("What does the excerpt say about the memo entitled Aurora Calibration Log?", "The memo entitled Aurora Calibration Log is short."),
        ("What does the excerpt titled e.e. cummings say?", None),  # no source: the title cannot be backed
        ("Em Outubro, Quanto foi pago?", "Em Outubro foi pago o valor."),
        ("Em Outubro, Quantos ocorreram?", "Em Outubro ocorreram três."),
        # codex pass 13: Portuguese question words, Russian calendar inflections, "titled this", 根据这份报告
        ("Em Outubro, Qual evento ocorreu?", "Em Outubro ocorreu a feira."),
        ("Какое событие произошло в Октябре?", "В Октябре произошла выставка."),
        ("What did the excerpt titled this say about Barry Cohen?", "Barry Cohen wrote about EJM."),
        ("根据这份报告，哪款车型销量最高？", "这份报告显示雅阁销量最高。"),
        ("明日はどこに行きますか？", "明日は大阪に行きます。"),
        # codex pass 12: capitalized question words after ¿ / calendar words in fr/es; pronoun-only with a date
        ("¿Qué evento ocurrió en Octubre?", "En Octubre ocurrió la feria."),
        ("Quel événement a eu lieu en Octobre ?", "En Octobre a eu lieu le salon."),
        ("What does the excerpt titled e.e. cummings say?", "Nothing about that here."),  # title absent from the source
        ("根据本报告，哪款车型销量最高？", "本报告显示雅阁销量最高。"),
        ("根據本報告，哪款車型銷量最高？", "本報告顯示雅閣銷量最高。"),
        # codex pass 11: a date anchors time, never a pronominal subject; reflexives are pronouns
        ("What did he do in October 2017?", "In October 2017 he flew to Paris."),
        ("他在2017年做了什么？", "他在2017年去了北京。"),
        ("그는 2017년에 무엇을 했나요?", "그는 2017년에 서울에 갔다."),
        ("自分は何を売りましたか？", "自分は車を売りました。"),
        ("자신은 무엇을 썼나요?", "자신은 편지를 썼다."),
        ("What happened on Monday?", None),
        # codex pass 11: "the email about X" qualifies the document at hand, it does not identify it
        ("What does the email about Barry Cohen say?", "Barry Cohen wrote about EJM."),
        # codex pass 10: relative time/place words are deixis, not entities
        ("他昨天去了哪里？", "他昨天去了北京。"),
        ("きのうはどこにいましたか？", "きのうはいえにいました"),
        ("그는 어제 무엇을 했나요?", "그는 어제 무엇을 했나요"),
        # codex pass 10: the "identified document" exception needs an identifier, not a pronoun or a relative day
        ("What did the email from him say about Barry Cohen?", None),
        ("What happened in the email from yesterday concerning Barry Cohen?", None),
        # bare references with trailing qualifiers (codex pass 9)
        ("What happened in the email about Barry Cohen in October?", None),
        ("What information in the email concerns Barry Cohen?", None),
        ("What was mentioned in the email about EJM?", None),
        ("What can be learned from the email about Barry Cohen?", None),
        ("What does the email say about Barry Cohen?", "Barry Cohen wrote about EJM."),
        ("Who does the document name as the Aurora pilot?", "The Aurora pilot is Kim."),
        ("What is stated in the email?", None),
        ("根据这封邮件，他说了什么事情？", "他说了什么事情"),  # source-referential (zh)
        ("このメールによると、彼は何を言いましたか？", "彼は何を言いましたか"),  # source-referential (ja)
        ("Что говорится в этом письме о Джеффри Эпштейне?", None),  # source-referential (ru) despite a name
        ("Что Эпштейн написал в тексте выше?", None),  # (ru) "in the text above"
        ("Selon ce courriel, que dit Jeffrey Epstein ?", None),  # source-referential (fr)
        ("Barry Cohen called Jeffrey Epstein in October;", None),  # ';' is a question mark only in Greek text
        ("What did he say in his friend's note about its plane's size?", None),  # possessives are not quotes
    ],
)
def test_self_contained_guard_still_rejects_unanchored_or_source_referential_questions(question: str, excerpt: str | None) -> None:
    assert not is_self_contained_question(question, source_excerpt=excerpt)


@pytest.mark.parametrize(
    ("question", "excerpt"),
    [
        # a sentence-initial name is an anchor when the source writes it capitalized mid-sentence
        ("Aurora recorded what salinity after calibration?", "The Aurora buoy recorded 34.2 PSU after calibration."),
        ("Epstein asked whom to call in October?", "Barry wrote that Epstein asked him to call."),
        # a quoted phrase anchors when it carries content and occurs in the source
        ("Who described the buoy array as 'drifting beyond tolerance' in the log?", "The log says: drifting beyond tolerance."),
        ("Who described the buoy array as 'drifting beyond tolerance' in the log?", None),
        ("Was it Barry Cohen who recommended EJM in 2017?", None),
        # codex pass 18: pronoun offsets come from the original string ("Shepherd" contains "he"); an
        # explicit role wins over the -ing heuristic; a hangul name binds a Korean possessive
        ("Shepherd: did he call Barry Cohen in October 2017?", "Shepherd called Barry Cohen."),
        ("Which king changed his route in October 2017?", "The king changed his route."),
        ("Which king said he called Barry Cohen in October 2017?", "The king said he called Barry Cohen."),
        ("김민수가 그의 경로를 변경했나요?", "김민수가 그의 경로를 변경했다."),
        # codex pass 17: any bounded cleft focus; animate interrogative heads bind embedded pronouns and
        # possessives; grammatical-gender possessives (son/su) need only a nominal antecedent
        ("Was it because of the 2017 regulation that EJM changed its policy?", "EJM changed its policy because of the 2017 regulation."),
        ("Was it due to the 2017 regulation that EJM changed its policy?", "EJM changed its policy due to the 2017 regulation."),
        ("Was it between October and November 2017 that Barry Cohen managed the plane?", "Barry Cohen managed the plane between October and November 2017."),
        ("Was it the 2017 regulation that EJM changed its policy?", "EJM changed its policy after the 2017 regulation."),
        ("Which witness said he called Barry Cohen in October 2017?", "The witness Kim said he called Barry Cohen."),
        ("Who said he called Barry Cohen in October 2017?", None),
        ("Which pilot changed his route in October 2017?", "The pilot changed his route."),
        ("Quelle entreprise a changé son siège social en octobre 2017 ?", "L'entreprise Aurora a changé son siège social."),
        ("¿Qué empresa cambió su sede en octubre de 2017?", "La empresa Aurora cambió su sede."),
        # codex pass 16: prepositional cleft focus, sentence-initial antecedent with a colon, resolved
        # reporting-clause subject, possessive resolved by a named person
        ("Was it in October 2017 that Barry Cohen recommended EJM?", "In October 2017 Barry Cohen recommended EJM."),
        ("Epstein: why did he recommend EJM in 2017?", "Epstein recommended EJM in 2017."),
        ("Which witness statement said Epstein called Barry Cohen in October 2017?", None),
        ("Which companies changed their policies after Epstein's arrest in October 2017?", None),
        # codex pass 15: clefts, resolved pronouns and resolved possessives stay accepted
        ("Which of the 2017 regulations was it that required emissions disclosure?", "The 2017 regulations required emissions disclosure."),
        ("What did Barry Cohen say when he called EJM?", None),
        ("What did Barry Cohen write about his plane in October 2017?", None),
        ("张伟的名字是什么？", "张伟的名字是张伟。"),
        ("What does the excerpt, titled 'Aurora Calibration Log', say?", "Aurora Calibration Log: drift."),
        # a *named* document is a subject, not a bare discourse reference
        ("What did the email from Barry Cohen say about EJM?", "Barry Cohen wrote about EJM."),
        ("What did Epstein write in the email to Cohen?", None),
        ("What did the memo dated 2017-10-03 instruct Barry Cohen to do?", None),
        # codex pass 13: an object pronoun in a later clause is not the subject; a deictic span inside
        # a source-backed name (明日香) is a name; "according to this 2017 regulation" names its subject
        ("Which 2017 regulation did the agency say it enforced?", "The agency said it enforced the 2017 regulation."),
        ("明日香はどこで生まれましたか？", "明日香は大阪で生まれました。"),
        ("根据这项2017年法规，哪些公司必须披露排放？", "这项2017年法规要求公司披露排放。"),
        ("Какое событие произошло в Октябре на буе Aurora?", "В Октябре на буе Aurora произошла калибровка."),
        # codex pass 12: object/possessive pronouns do not make the subject pronominal; titles identify
        # whatever their case; a name may contain a grammar character (上野)
        ("Which 2017 regulation required companies to disclose their emissions?", "The 2017 regulation required companies to disclose their emissions."),
        ("What does the excerpt titled e.e. cummings say?", "e.e. cummings wrote poems."),
        ("¿Qué empresa de gestión de aviones recomendó Barry Cohen en octubre de 2017?", None),
        ("上野是谁？", "上野是东京的一个区。"),
        # codex pass 11: a named/titled source is a subject; a date anchors a non-pronominal question
        ("根据本田公司的报告，哪款车型销量最高？", "本田公司的报告显示雅阁销量最高。"),
        ("In the excerpt titled “Aurora Calibration Log”, which sensor drifted?", "Aurora Calibration Log: the salinity sensor drifted."),
        ("What did the buoy report on 2017-10-03?", "The buoy reported 34 PSU on 2017-10-03."),
        ("Which flights did Epstein test on the Gulfstream in 2017?", None),
    ],
)
def test_source_aware_anchors_accept_real_entity_bearing_questions(question: str, excerpt: str | None) -> None:
    assert is_real_query(question)
    assert is_self_contained_question(question, source_excerpt=excerpt)


def test_answer_is_anchored_requires_the_answer_content_in_the_excerpt() -> None:
    assert answer_is_anchored("EJM", EMAIL)
    assert answer_is_anchored("switching from Jet Aviation to EJM", EMAIL)
    assert answer_is_anchored('"Plane management"', EMAIL)
    assert not answer_is_anchored("A company on Mars", EMAIL)
    assert not answer_is_anchored("", EMAIL)
    # whole-token matching: "Ann" is not anchored by "planning"
    assert not answer_is_anchored("Ann", "The planning meeting moved to Tuesday.")
    assert answer_is_anchored("张伟", "发件人是张伟。")
    assert answer_is_anchored("Эпштейн", "Письмо отправил Эпштейн.")


def test_judge_state_carries_the_row_its_document_and_the_located_span_not_the_excerpt() -> None:
    item = EvalDatasetItem(
        question="Which plane management company did Barry Cohen consider switching to from Jet Aviation?",
        expected_paths=[EMAIL_PATH],
        expected_locations=[EMAIL_LOCATION],
        expected_answer="EJM",
        evidence_quote="switching from Jet Aviation to EJM",
    )
    state = judge_state(item, source_path=EMAIL_PATH)
    assert state == {
        "document": EMAIL_PATH,
        "answer_location": "lines 1-3",
        "row": {
            "question": item.question,
            "expected_answer": "EJM",
            "evidence_quote": "switching from Jet Aviation to EJM",
        },
    }
    one_page = item.model_copy(
        update={
            "expected_paths": ["A11_MissionReport.pdf"],
            "expected_locations": [EvalExpectedLocation(path="A11_MissionReport.pdf", unit="page", start=72, end=72)],
        }
    )
    assert judge_state(one_page, source_path="A11_MissionReport.pdf")["answer_location"] == "page 72"


def test_every_judge_question_is_a_noul_with_true_and_false_criteria_and_the_state_paths_it_names() -> None:
    assert set(JUDGE_QUESTIONS) == {READER_QUESTION, ANSWER_SUPPORTED, ANSWER_CUED}
    state = judge_state(
        EvalDatasetItem(question="q", expected_paths=[EMAIL_PATH], expected_locations=[EMAIL_LOCATION]),
        source_path=EMAIL_PATH,
    )
    for question in JUDGE_QUESTIONS.values():
        assert question.type == "noul"
        assert question.criteria is not None and question.criteria.true and question.criteria.false
        # Every backticked path the question points at must exist in the state judge_state builds.
        refs = re.findall(r"`([^`]+)`", str(question.instructions))
        assert refs
        for ref in refs:
            node: object = state
            for part in ref.split("."):
                assert isinstance(node, dict) and part in node, f"{ref!r} is not in the judge state"
                node = node[part]
    reader = JUDGE_QUESTIONS[READER_QUESTION]
    # The eval agent's two basic-logic rules survive the move off the LLM prompt.
    assert "cover or title-page" in str(reader.criteria.false) and "filename" in str(reader.criteria.false)
    assert "file name or path" in str(JUDGE_QUESTIONS[ANSWER_SUPPORTED].criteria.false)


def test_judge_verdict_requires_every_question_answered() -> None:
    verdict = judge_verdict({READER_QUESTION: 0.9, ANSWER_SUPPORTED: 0.8, ANSWER_CUED: 0.1})
    assert verdict == JudgeVerdict(reader_question=0.9, answer_supported=0.8, answer_cued=0.1)
    with pytest.raises(KeyError):
        judge_verdict({READER_QUESTION: 0.9, ANSWER_SUPPORTED: 0.8})


def test_source_excerpt_caps_lines() -> None:
    content = "\n".join(f"line {i}" for i in range(1, 11))
    assert source_excerpt(content, max_lines=3) == "line 1\nline 2\nline 3"
    assert source_excerpt(content, max_lines=50) == content


def test_build_eval_item_enforces_limits_and_tags() -> None:
    limits = SyntheticGeneratorConfig(question_max_chars=80, expected_answer_max_chars=50)
    row = {
        "question": "Which plane management company did Barry Cohen consider switching to?",
        "expected_answer": "EJM",
        "evidence_quote": "switching from Jet Aviation to EJM",
    }
    item = build_eval_item(
        row,
        source_path=EMAIL_PATH,
        location=EMAIL_LOCATION,
        source_kind="document",
        include_expected_answer=True,
        include_tags=True,
        limits=limits,
    )
    assert item is not None
    assert item.expected_paths == [EMAIL_PATH]
    assert item.expected_answer == "EJM"
    assert item.evidence_quote == "switching from Jet Aviation to EJM"
    assert item.tags == ["synthetic", "grounded_qa", "document"]

    too_long = dict(row, question="Which plane management company did Barry Cohen consider switching to from Jet Aviation in 2017?")
    assert build_eval_item(
        too_long,
        source_path=EMAIL_PATH,
        location=EMAIL_LOCATION,
        source_kind="document",
        include_expected_answer=True,
        include_tags=True,
        limits=limits,
    ) is None

    # the generated answer stays on the row for judging and mining; publication drops it on request
    from server.synthetic.providers.grounded_qa_provider import publish_item

    retained = build_eval_item(
        row,
        source_path=EMAIL_PATH,
        location=EMAIL_LOCATION,
        source_kind="document",
        include_expected_answer=False,
        include_tags=False,
        limits=limits,
    )
    assert retained is not None
    assert retained.expected_answer == "EJM"
    assert retained.tags == []
    assert publish_item(retained, include_expected_answer=False).expected_answer == ""
    assert publish_item(retained, include_expected_answer=True).expected_answer == "EJM"


def _pdf_chunk(page_start: int, page_end: int) -> Chunk:
    return Chunk(
        chunk_id="pytest_pdf_chunk",
        content="The descent engine was throttled to 55 percent at 7 minutes into powered descent.",
        file_path="A11_MissionReport.pdf",
        start_line=3056,
        end_line=3092,
        provenance=ChunkProvenance(
            extraction="docling",
            page_start=page_start,
            page_end=page_end,
            regions=[PageRegion(page=page_start, left=0.1, top=0.1, right=0.9, bottom=0.5)],
        ),
    )


def test_source_location_is_the_page_span_for_paged_documents_and_the_line_span_otherwise() -> None:
    assert source_location(_pdf_chunk(176, 179)) == EvalExpectedLocation(
        path="A11_MissionReport.pdf", unit="page", start=176, end=179
    )
    text_chunk = Chunk(chunk_id="pytest_txt", content=EMAIL, file_path=EMAIL_PATH, start_line=120, end_line=180)
    assert source_location(text_chunk) == EvalExpectedLocation(path=EMAIL_PATH, unit="line", start=120, end=180)
    # A chunk with neither page provenance nor a line span cannot be located.
    unlocated = Chunk(chunk_id="pytest_none", content=EMAIL, file_path=EMAIL_PATH, start_line=0, end_line=0)
    assert source_location(unlocated) is None


def test_whole_document_rows_are_rejected_and_located_rows_are_kept() -> None:
    """A row whose only evidence is the whole file can never fail on a single-document corpus."""
    limits = SyntheticGeneratorConfig()
    row = {
        "question": "To what percent was the Apollo 11 descent engine throttled seven minutes into powered descent?",
        "expected_answer": "55 percent",
        "evidence_quote": "throttled to 55 percent",
    }
    common = {
        "source_path": "A11_MissionReport.pdf",
        "source_kind": "document",
        "include_expected_answer": True,
        "include_tags": True,
        "limits": limits,
    }
    assert build_eval_item(row, location=None, **common) is None

    located = source_location(_pdf_chunk(176, 179))
    item = build_eval_item(row, location=located, **common)
    assert item is not None
    assert item.expected_paths == ["A11_MissionReport.pdf"]
    assert item.expected_locations == [
        EvalExpectedLocation(path="A11_MissionReport.pdf", unit="page", start=176, end=179)
    ]


@pytest.mark.parametrize(
    ("reader", "supported", "cued", "thresholds", "kept"),
    [
        # Both gated nouls at or above their minimums: kept (the minimum is inclusive).
        (0.95, 0.93, 0.02, SyntheticJudgeConfig(), True),
        (0.70, 0.70, 0.99, SyntheticJudgeConfig(), True),
        # Either gate below its minimum drops the row, whatever the other says.
        (0.69, 0.99, 0.0, SyntheticJudgeConfig(), False),
        (0.99, 0.69, 0.0, SyntheticJudgeConfig(), False),
        # Cover-page trivia measured on nasa-apollo-11 (reader 0.07-0.61) never passes the default.
        (0.61, 0.97, 0.9, SyntheticJudgeConfig(), False),
        (0.07, 0.97, 0.9, SyntheticJudgeConfig(), False),
        # The minimums are the operator's: each gate moves independently.
        (0.50, 0.95, 0.0, SyntheticJudgeConfig(reader_question_min=0.5), True),
        (0.95, 0.50, 0.0, SyntheticJudgeConfig(answer_supported_min=0.5), True),
        (0.95, 0.95, 0.0, SyntheticJudgeConfig(reader_question_min=1.0), False),
        (0.0, 0.0, 0.0, SyntheticJudgeConfig(reader_question_min=0.0, answer_supported_min=0.0), True),
    ],
)
def test_judge_keeps_a_row_only_when_every_gated_noul_reaches_its_minimum(
    reader: float, supported: float, cued: float, thresholds: SyntheticJudgeConfig, kept: bool
) -> None:
    verdict = JudgeVerdict(reader_question=reader, answer_supported=supported, answer_cued=cued)
    assert judge_accepts(verdict, thresholds) is kept


def test_judge_thresholds_are_probabilities() -> None:
    for field_name in ("reader_question_min", "answer_supported_min"):
        with pytest.raises(ValueError):
            SyntheticJudgeConfig(**{field_name: 1.5})
        with pytest.raises(ValueError):
            SyntheticJudgeConfig(**{field_name: -0.1})
