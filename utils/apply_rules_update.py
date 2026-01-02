import os

def update_rules():
    rule_path = os.path.join(os.getcwd(), ".agent", "rules", "anti-stock.md")
    if not os.path.exists(rule_path):
        print(f"Error: {rule_path} not found.")
        return

    with open(rule_path, "r", encoding="utf-8") as f:
        content = f.read()

    new_rule = """
### Testing & Debugging Rules
- 모든 테스트 프로그램, 디버깅 스크립트, 임시 검증 코드는 반드시 루트 폴더가 아닌 `tests/` 폴더 내에 작성한다.
- 테스트 완료 후 불필요해진 스크립트는 즉시 삭제하거나 `tests/` 폴더 내에 정리하여 프로젝트 루트의 청결을 유지한다.
"""

    if "### Testing & Debugging Rules" not in content:
        # Insert before "When generating documentation"
        target = "When generating documentation"
        if target in content:
            content = content.replace(target, new_rule + "\n" + target)
            with open(rule_path, "w", encoding="utf-8") as f:
                f.write(content)
            print("Rules updated successfully.")
        else:
            # Fallback to append
            content += "\n" + new_rule
            with open(rule_path, "w", encoding="utf-8") as f:
                f.write(content)
            print("Rules updated (appended) successfully.")
    else:
        print("Rules already exist.")

if __name__ == "__main__":
    update_rules()
