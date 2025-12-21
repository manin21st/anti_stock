# AntiGravity Agent Custom Instructions

These instructions define the operating parameters for the AntiGravity agent. They are designed to be modular and extensible.

## 1. Global Communication Standards
*   **Primary Language**: You must communicate, plan, and document everything in **Korean** (한국어). This applies to:
    *   Implementation Plans (계획서)
    *   Task Lists (`task.md`)
    *   Walkthroughs
    *   General Chat Responses
    *   Code Comments (where appropriate for context)
*   **Exceptions**: Use English only for code syntax, standard technical terminology, or when explicitly requested by the user.

## 2. Runtime Environment Guidelines (Windows)
*   **Command Prefix**: All terminal/shell commands MUST be executed using the `cmd /c` prefix.
    *   ✅ Correct: `cmd /c python main.py`
    *   ❌ Incorrect: `python main.py`
*   **Prohibited Commands**: The usage of `chcp` (Change Code Page) is **strictly prohibited**. Do not attempt to change the console encoding; assume the environment is pre-configured correctly.

## 3. Development Workflow & Organization
*   **Test File Isolation**: All scripts created for testing, debugging, verification, or validation purposes MUST be located in the `tests/` directory.
    *   **Action**: If a temporary script is needed (e.g., `verify_api.py`, `debug_crash.py`), create it directly in `tests/`.
    *   **Cleanup**: Do not leave temporary scripts in the project root directory.

## 4. Future Extensions
*   (Add new sections here as needed)
