import ast

from memory_os.lora.training_config import LoraTrainingConfig


def _reward_namespace(script: str) -> dict:
    tree = ast.parse(script)
    function_names = {"_completion_text", "_available_actions", "reward_action_router"}
    body = []
    for node in tree.body:
        if isinstance(node, ast.Import) and any(alias.name in {"json", "re"} for alias in node.names):
            body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in function_names:
            body.append(node)
    namespace = {}
    exec(compile(ast.Module(body=body, type_ignores=[]), "<reward>", "exec"), namespace)
    return namespace


def test_grpo_script_renders_working_action_reward_verifier():
    script = LoraTrainingConfig(
        name="action-router",
        base_model="example/model",
        dataset_path="train.jsonl",
        output_dir="output",
        method="grpo",
    ).render_script()
    reward = _reward_namespace(script)["reward_action_router"]
    prompt = (
        "<available_actions>\n"
        "memory.search: Search memory.\n"
        "file.read: Read a file.\n"
        "</available_actions>"
    )

    rewards = reward(
        completions=[
            '{"action":"memory.search","args":{"query":"routing"}}',
            [{"role": "assistant", "content": '{"action":"file.read","args":{"path":"README.md"}}'}],
            '{"action":"shell.exec","args":{}}',
            '{"action":"memory.search","args":{},"extra":true}',
            "not json",
        ],
        prompts=[[{"role": "system", "content": "Route actions."}, {"role": "user", "content": prompt}]] * 5,
    )

    assert rewards == [1.0, 1.0, 0.0, 0.0, 0.0]
    assert "TODO" not in script
    assert "NotImplementedError" not in script


def test_grpo_reward_rejects_completion_without_prompt_vocabulary():
    script = LoraTrainingConfig(
        name="action-router",
        base_model="example/model",
        dataset_path="train.jsonl",
        output_dir="output",
        method="grpo",
    ).render_script()
    reward = _reward_namespace(script)["reward_action_router"]

    assert reward(
        completions=['{"action":"memory.search","args":{}}'],
        prompts=["plain prompt"],
    ) == [0.0]
