# This is just a utility class that defines and runs the client_wrapper.
import os
from guardrails_simlab_client import simlab_connect, custom_judge, JudgeResult
from litellm import litellm

CONTROL_PLANE_URL = os.getenv("CONTROL_PLANE_URL", "http://gr-threat-tester-prod-ctrl-svc.gr-threat-tester-prod.priv.local:8080")


@custom_judge(
    risk_name="example",
    enable=True,
    control_plane_host=CONTROL_PLANE_URL
)
def example_judge(
    user_message: str,
    bot_response: str
) -> JudgeResult:
    print(f"Running example_judge on user_message: {user_message} and bot_response: {bot_response}")
    return JudgeResult(
        justification="This is a test",
        triggered=False
    )

@simlab_connect(
    enable=True, 
    control_plane_host=CONTROL_PLANE_URL
)
def generate_with_huge_llm(messages) -> str:
    print(f"Running generate_with_huge_llm: {messages}")
    res = litellm.completion(
        model="gpt-4o-mini",
        messages=messages
    )
    return res.choices[0].message.content

print("Loaded example.py")

if __name__ == '__main__':
    print("Running example.py")
    prompt = "It was the best of times, it was the worst of times."
    out = generate_with_huge_llm([{
        "role": "user", 
        "content": prompt
    }])
    # Nothing below here will happen bc above is blocking
    print(out)

    judge_out = example_judge(prompt, out)
    print(judge_out)