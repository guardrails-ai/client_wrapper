# Sim Lab Client SDK

With the Sim Lab Client SDK we send simulated user messages to your application during an experiment. 

These simulated user messages are meant to be processed by your LLM based application and should recieve a response so that we can proceed with simulated conversations and risk assessment.

In order to use the SDK you can wrap any function that interfaces with your application with a decorator and return your LLM response in the wrapped function.

## Installation

```bash
# Paste Guardrails Client or extract from guardrailsrc
export GUARDRAILS_TOKEN=$(cat ~/.guardrailsrc| awk -F 'token=' '{print $2}' | awk '{print $1}' | tr -d '\n')

# Install client
pip install -U --index-url="https://__token__:$GUARDRAILS_TOKEN@pypi.guardrailsai.com/simple" \
    --extra-index-url="https://pypi.org/simple" guardrails-ai-simlab-client
```

## Sample llm Usage

```python
from guardrails_simlab_client import simlab_connect

@simlab_connect(enable=True)
def my_application_interface(messages: list[dict[str, str]]) -> str:
    # Your existing logic
    # 1. Call LLM API directly
    # 2. HTTP call to your application
    
    # Lastly, return LLM application response

    # Example using litellm
    import litellm
    res = litellm.completion(
        model="gpt-4o-mini",
        messages=messages
    )
    return res.choices[0].message.content
```

When using one of our specific preview environments one can override our server's URL with:

```python
@simlab_connect(enable=True, control_plane_host="http://...")
def my_application_interface(user_message):
    ...
```

## Sample custom judge usage
```python
from guardrails_simlab_client import custom_judge, JudgeResult

@custom_judge(
    risk_name="Toxic Language",
    enable=True,
    application_id="41bddba7-feaf-40e2-ba28-9daf22a1ec71"
)
def custom_judge_fn(
    user_message: str,
    bot_response: str,
    messages: dict[str, str] # full conversation history
) -> JudgeResult:
    # Your existing logic
    # 1. Call custom LLM judge API directly
    # 2. execute code judge regex, complex algs etc
    
    # Lastly, return JudgeResult
    if "obscenity" in bot_response.lower():
        return JudgeResult(
            justification="Detected use of inappropriate language: 'obscenity'",
            triggered=True,
        )
    return JudgeResult(
            justification="No inappropriate language",
            triggered=False,
    )
```

