# Client-side Socket Python Wrapper + Code-level Annotation

This document provides an example of how to use the client-side socket Python wrapper with code-level annotation.

## Sample Usage

### my_py.py

```python
from client_wrapper import tt_webhook_polling_sync

@tt_webhook_polling_sync(enable=True, control_plane_host="http://localhost:8080")
def some_func(prompt):
    # YOUR EXISTING LLM LOGIC

    # SOME STRING RESULT
    return res