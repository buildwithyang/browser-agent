from app.render import render_markdown


def test_render_basic_markdown():
    html = render_markdown("# Title\n\nSome **bold** text and a list:\n\n- a\n- b")

    assert "<h1>" in html
    assert "<strong>bold</strong>" in html
    assert "<li>a</li>" in html


def test_render_strips_dangerous_html():
    html = render_markdown(
        "ok <script>alert(1)</script> <img src=x onerror=alert(1)>"
    )

    assert "<script>" not in html
    assert "onerror" not in html
