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
    --extra-index-url="https://pypi.org/simple" guardrails-grhub-simlab-client
```

## Sample Usage

```python
from client_wrapper import tt_webhook_polling_sync

@tt_webhook_polling_sync(enable=True)
def my_application_interface(user_message):
    # Your existing logic
    # 1. Call LLM API directly
    # 2. HTTP call to your application
    
    # Lastly, return LLM application response

    # Example using litellm
    import litellm
    res = litellm.completion(
        model="gpt-4o-mini",
        messages=[{ "role": "user", "content": user_message }]
    )
    return res.choices[0].message.content
```

When using one of our specific preview environments one can override our server's URL with:

```python
@tt_webhook_polling_sync(enable=True, control_plane_host="http://...")
def my_application_interface(user_message):
    ...
```