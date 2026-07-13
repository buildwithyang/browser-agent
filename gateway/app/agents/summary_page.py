from app.agents.base import OpenAIChatAgent
from app.modules.task.schema import Action, AgentName, QuickInsight, TaskCreate
from app.render import render_markdown

SYSTEM_PROMPT = (
    "你是 Agent Bridge 的网页摘要助手。用户会把当前正在浏览的网页内容发给你,"
    "目标是让他不点进去、不通读全文,也能在几秒内抓住这个页面最重要的信息。"
    "请用 Markdown 按以下结构输出:\n"
    "- 第一段:用一句话直接给出这个页面【最值得知道的核心结论】——浓缩最关键的"
    "事实、数字或判断,让人据此就能做决定。不要写「这是一个……页面」这类描述页面"
    "类型的话,单独成段。\n"
    "- 随后给出 3-6 条关键要点的无序列表,每条以一个**加粗的关键词**开头,后接简短说明,"
    "按重要性从高到低排列。\n"
    "保持简洁,忠于原文,不要编造页面中没有的信息。"
)


class SummaryPageAgent(OpenAIChatAgent):
    name = AgentName.SUMMARY_PAGE
    system_prompt = SYSTEM_PROMPT

    def build_prompt(self, task: TaskCreate) -> str:
        selection = task.selected_text.strip()
        # 选中文字非空 = 用户明确的"我只关心这块"信号:只总结选中内容,
        # 页面标题/URL 仅作轻背景,不灌整页正文(也更快、更省 token)。
        if selection:
            return "\n".join(
                [
                    "User intent:",
                    "The user highlighted a specific passage on the page. "
                    "Summarize ONLY this selected passage. Use the page title/URL "
                    "as light context; do not summarize the rest of the page.",
                    "",
                    "Selected text:",
                    selection,
                    "",
                    "Page title:",
                    task.title,
                    "",
                    "Page URL:",
                    task.url,
                ]
            )
        # 没有选中 -> 总结整页
        return "\n".join(
            [
                "User intent:",
                task.intent.strip(),
                "",
                "Page URL:",
                task.url,
                "",
                "Page title:",
                task.title,
                "",
                "Page text:",
                task.page_text.strip() or "(none)",
                "",
                "Image clues (alt/caption/aria-label):",
                task.image_text.strip() or "(none)",
            ]
        )

    def build_insight(self, result: str, lang: str) -> QuickInsight:
        return QuickInsight(
            type="summary",
            title="Page Summary" if lang == "en" else "页面摘要",
            summary_html=render_markdown(result),
        )

    def actions(self, task: TaskCreate, lang: str) -> list[Action]:
        return [
            Action(
                id="ask_more",
                label="Ask more" if lang == "en" else "继续提问",
                task_type="ask_more",
                enabled=False,
            )
        ]
