from app.agents.base import OpenAIChatAgent
from app.models import TaskCreate

SYSTEM_PROMPT = (
    "你是 Agent Bridge 的网页摘要助手。用户会把当前正在浏览的网页内容发给你,"
    "目标是让他不点进去、不通读全文,也能在几秒内抓住这个页面最重要的信息。"
    "请始终用中文回复,并用 Markdown 按以下结构输出:\n"
    "- 第一段:用一句话直接给出这个页面【最值得知道的核心结论】——浓缩最关键的"
    "事实、数字或判断,让人据此就能做决定。不要写「这是一个……页面」这类描述页面"
    "类型的话,单独成段。\n"
    "- 随后给出 3-6 条关键要点的无序列表,每条以一个**加粗的关键词**开头,后接简短说明,"
    "按重要性从高到低排列。\n"
    "保持简洁,忠于原文,不要编造页面中没有的信息。"
)


class SummaryPageAgent(OpenAIChatAgent):
    name = "summary_page"
    system_prompt = SYSTEM_PROMPT

    def build_prompt(self, task: TaskCreate) -> str:
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
                "Selected text:",
                task.selected_text.strip() or "(none)",
                "",
                "Page text:",
                task.page_text.strip() or "(none)",
            ]
        )
