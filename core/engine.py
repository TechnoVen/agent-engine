from typing import Any, Callable, Dict, List, Optional, Union

import dspy
from pydantic import BaseModel, Field


class NodeConfig(BaseModel):
    """
    Schema representation for a visual low-code blueprint node.
    """

    name: str = Field(default="DynamicAgent", description="Identifier name of the agent node")
    description: str = Field(
        default="Perform task logic according to inputs and outputs.",
        description="Agent objective/instructions",
    )
    inputs: Union[List[str], Dict[str, str]] = Field(
        default_factory=list, description="Input fields list or {field_name: field_desc}"
    )
    outputs: Union[List[str], Dict[str, str]] = Field(
        default_factory=list, description="Output fields list or {field_name: field_desc}"
    )
    tools: List[str] = Field(default_factory=list, description="List of registered tool names")
    reasoning_type: str = Field(
        default="cot",
        description="Reasoning type: 'cot' (ChainOfThought), 'react' (ReAct), or 'predict'",
    )


class DynamicSignatureBuilder:
    """
    Dynamically constructs a DSPy Signature class from declarative blueprint schemas.
    """

    @staticmethod
    def build(config: Union[NodeConfig, Dict[str, Any]]) -> type:
        if isinstance(config, dict):
            config = NodeConfig(**config)

        fields: Dict[str, Any] = {}

        # 1. Process Input Fields
        if isinstance(config.inputs, list):
            for inp in config.inputs:
                fields[inp] = dspy.InputField(desc=f"Input parameter: {inp}")
        elif isinstance(config.inputs, dict):
            for inp, desc in config.inputs.items():
                fields[inp] = dspy.InputField(desc=desc)

        # 2. Process Output Fields
        if isinstance(config.outputs, list):
            for out in config.outputs:
                fields[out] = dspy.OutputField(desc=f"Output result: {out}")
        elif isinstance(config.outputs, dict):
            for out, desc in config.outputs.items():
                fields[out] = dspy.OutputField(desc=desc)

        # 3. Create Dynamic Subclass of dspy.Signature
        safe_name = "".join(c for c in config.name if c.isalnum() or c == "_") or "DynamicAgent"
        sig_class = type(f"{safe_name}Signature", (dspy.Signature,), fields)
        sig_class.__doc__ = config.description
        return sig_class


# Tool Registry for mapping tool names to actual Python functions
_GLOBAL_TOOL_REGISTRY: Dict[str, Callable] = {}


def register_tool(name: str):
    """Decorator to register a tool function in the global registry."""

    def decorator(fn: Callable):
        _GLOBAL_TOOL_REGISTRY[name] = fn
        return fn

    return decorator


# Built-in sample tools
@register_tool("calculator")
def calculator_tool(expression: str) -> str:
    """Evaluate a mathematical expression safely."""
    try:
        # Simple arithmetic evaluator for safety
        allowed = set("0123456789+-*/(). %")
        if all(c in allowed for c in expression.strip()):
            return str(eval(expression.strip()))
        return "Error: Expression contains unsupported characters"
    except Exception as e:
        return f"Error: {e}"


@register_tool("system_info")
def system_info_tool(query: str = "") -> str:
    """Retrieve local system details."""
    import platform

    return f"OS: {platform.system()} {platform.release()} | Machine: {platform.machine()}"


class LowCodeAgent(dspy.Module):
    """
    Dynamic DSPy Module compiled on-the-fly from a low-code visual blueprint.
    """

    def __init__(
        self,
        config: Union[NodeConfig, Dict[str, Any]],
        tool_registry: Optional[Dict[str, Callable]] = None,
    ):
        super().__init__()
        if isinstance(config, dict):
            config = NodeConfig(**config)

        self.config = config
        self.signature = DynamicSignatureBuilder.build(config)
        self.tool_map = tool_registry or _GLOBAL_TOOL_REGISTRY

        # Determine tools
        active_tools = []
        for t_name in config.tools:
            if t_name in self.tool_map:
                active_tools.append(self.tool_map[t_name])

        # Select DSPy processor module
        r_type = config.reasoning_type.lower()
        if r_type == "react" or (len(active_tools) > 0 and r_type != "cot"):
            self.processor = dspy.ReAct(self.signature, tools=active_tools)
        elif r_type == "predict":
            self.processor = dspy.Predict(self.signature)
        else:
            # Default to Chain of Thought
            self.processor = dspy.ChainOfThought(self.signature)

    def forward(self, **kwargs) -> dspy.Prediction:
        """Execute the compiled agent with provided input parameters."""
        return self.processor(**kwargs)

    def __repr__(self) -> str:
        return f"<LowCodeAgent name='{self.config.name}' reasoning='{self.config.reasoning_type}' inputs={list(self.config.inputs)} outputs={list(self.config.outputs)}>"


class AgentPipeline(dspy.Module):
    """
    Multi-Agent Sequential Pipeline connecting outputs of one agent to inputs of the next.
    """

    def __init__(self, steps: List[LowCodeAgent]):
        super().__init__()
        self.steps = steps

    def forward(self, **initial_inputs) -> Dict[str, Any]:
        state = dict(initial_inputs)
        execution_trace = []

        for idx, agent in enumerate(self.steps):
            # Extract inputs required by this agent
            agent_inputs = {}
            inp_keys = (
                agent.config.inputs
                if isinstance(agent.config.inputs, list)
                else list(agent.config.inputs.keys())
            )
            for key in inp_keys:
                if key in state:
                    agent_inputs[key] = state[key]

            prediction = agent(**agent_inputs)
            pred_dict = prediction.toDict() if hasattr(prediction, "toDict") else dict(prediction)

            # Update state with outputs
            state.update(pred_dict)
            execution_trace.append(
                {
                    "step": idx + 1,
                    "agent": agent.config.name,
                    "inputs": agent_inputs,
                    "outputs": pred_dict,
                }
            )

        return {"final_state": state, "trace": execution_trace}
