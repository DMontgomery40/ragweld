"""Corpus models - re-exported from THE LAW.

The repo previously used "repo" terminology. We are migrating to "corpus"
as the primary unit of isolation, but keep these legacy names for backwards
compatibility within the codebase during the transition.
"""

from server.models.tribrid_config_model import Corpus, CorpusStats

# Legacy aliases (preferred: Corpus / CorpusStats)
Repository = Corpus
RepoStats = CorpusStats

__all__ = ["Corpus", "CorpusStats", "Repository", "RepoStats"]
