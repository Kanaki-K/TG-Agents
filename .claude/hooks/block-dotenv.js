// PreToolUse-хук: блокирует любую Bash-команду, которая обращается к .env
// (cat/grep/tail/head/sed/node/awk и т.п.). Шаблоны .env.example / .env.sample
// не считаются секретами и пропускаются.
// Формат ввода/вывода: https://docs.claude.com/en/docs/claude-code/hooks
let input = "";
process.stdin.on("data", (d) => (input += d));
process.stdin.on("end", () => {
  let cmd = "";
  try {
    cmd = (JSON.parse(input).tool_input || {}).command || "";
  } catch (e) {
    /* кривой JSON — не блокируем, пусть решают штатные правила */
  }
  if (/\.env(?!\.(example|sample))/.test(cmd)) {
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "deny",
          permissionDecisionReason:
            "Доступ к .env заблокирован политикой безопасности (PreToolUse hook). Секреты защищены; чтобы временно снять — отключи хук в .claude/settings.local.json.",
        },
      })
    );
  }
  process.exit(0);
});
