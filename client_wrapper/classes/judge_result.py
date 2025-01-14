from typing import List

class JudgeResult:
    experiment_id: str = ""
    test_id: str = ""
    risk: str = ""
    justification: str = ""
    triggered: bool = False
    tags: List[str] = []

    def __init__(
        self,
        experiment_id: str,
        test_id: str,
        risk: str,
        justification: str,
        triggered: bool,
        tags: List[str],
    ):
        self.experiment_id = experiment_id
        self.test_id = test_id
        self.risk = risk
        self.justification = justification
        self.triggered = triggered
        self.tags = tags