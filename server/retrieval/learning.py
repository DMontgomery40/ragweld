from typing import Any

from server.models.eval import EvalResult


class LearningReranker:
    def __init__(self, base_model: str, output_dir: str):
        self.base_model = base_model
        self.output_dir = output_dir

    async def mine_triplets(self, repo_id: str, eval_results: list[EvalResult]) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def train(self, triplets: list[dict[str, Any]], epochs: int = 3) -> dict[str, Any]:
        raise NotImplementedError

    async def evaluate(self, test_triplets: list[dict[str, Any]]) -> dict[str, Any]:
        raise NotImplementedError

    def save_model(self, path: str) -> None:
        raise NotImplementedError

    def load_model(self, path: str) -> None:
        raise NotImplementedError
