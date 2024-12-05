# This is just a utility class that defines and runs the client_wrapper.
import os
from client_wrapper import tt_webhook_polling_sync
from litellm import litellm

CONTROL_PLANE_URL = os.getenv("CONTROL_PLANE_URL", "http://gr-threat-tester-demo-ctrl-svc.gr-threat-tester-demo.priv.local:8080")

@tt_webhook_polling_sync(enable=True, control_plane_host=CONTROL_PLANE_URL)
def generate_with_huge_llm(prompt: str) -> str:
    print(f"Running generate_with_huge_llm: {prompt}")
    res = litellm.completion(
        model="gpt-4o-mini",
        messages=[{
            "role": "user",
            "content": prompt
        }]
    )
    return res.choices[0].message.content

print("Loaded example.py")

if __name__ == '__main__':
    print("Running example.py")
    out = generate_with_huge_llm("It was the best of times, it was the worst of times.")
    print(out)