import dspy
from dspy.evaluate import Evaluate
from dspy.teleprompt import BootstrapFewShot
from typing import List, Callable, Optional, Dict, Any
from core.engine import LowCodeAgent, NodeConfig

class AgentHarness:
    """
    Automated evaluation and self-improvement optimization harness for DSPy agents.
    """
    @staticmethod
    def default_exact_metric(gold: dspy.Example, pred: dspy.Prediction, trace=None) -> bool:
        """Checks if prediction matches gold example for all target output fields."""
        for key in gold.keys():
            if key not in gold._inputs and hasattr(pred, key):
                gold_val = str(getattr(gold, key)).strip().lower()
                pred_val = str(getattr(pred, key)).strip().lower()
                if gold_val not in pred_val:
                    return False
        return True

    @staticmethod
    def evaluate(
        module: dspy.Module,
        dataset: List[dspy.Example],
        metric: Optional[Callable] = None,
        num_threads: int = 2
    ) -> float:
        """Run standard evaluation against a validation set."""
        eval_fn = metric or AgentHarness.default_exact_metric
        evaluator = Evaluate(
            devset=dataset,
            metric=eval_fn,
            num_threads=num_threads,
            display_progress=True
        )
        return evaluator(module)

    @staticmethod
    def optimize(
        student_module: dspy.Module,
        trainset: List[dspy.Example],
        metric: Optional[Callable] = None,
        max_bootstrapped_demos: int = 4,
        max_labeled_demos: int = 4
    ) -> dspy.Module:
        """
        Compile and optimize the DSPy agent using BootstrapFewShot teleprompter.
        """
        opt_metric = metric or AgentHarness.default_exact_metric
        teleprompter = BootstrapFewShot(
            metric=opt_metric,
            max_bootstrapped_demos=max_bootstrapped_demos,
            max_labeled_demos=max_labeled_demos
        )
        compiled_module = teleprompter.compile(student_module, trainset=trainset)
        return compiled_module


def train_and_optimize(
    agent_config: NodeConfig,
    dataset: List[dspy.Example],
    metric: Optional[Callable] = None
) -> LowCodeAgent:
    """
    High-level convenience function: Takes blueprint schema + dataset -> returns optimized agent.
    """
    base_agent = LowCodeAgent(agent_config)
    optimized = AgentHarness.optimize(base_agent, dataset, metric=metric)
    return optimized
