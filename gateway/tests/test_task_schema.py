from app.modules.task.schema import Action, TaskCreate, TaskResponse


def test_taskcreate_defaults_have_no_sections_or_prior_result():
    t = TaskCreate(url="https://x.com/j")
    assert t.sections is None
    assert t.prior_result is None


def test_taskcreate_accepts_sections_and_prior_result_camel_alias():
    t = TaskCreate(
        url="https://x.com/j",
        sections=["cover_letter", "resume_tips"],
        priorResult="@@SECTION conclusion\n匹配度 60。",
    )
    assert t.sections == ["cover_letter", "resume_tips"]
    assert t.prior_result.startswith("@@SECTION conclusion")


def test_taskresponse_actions_default_empty():
    r = TaskResponse(request=TaskCreate(url="https://x.com/j"))
    assert r.actions == []


def test_action_model_shape():
    a = Action(id="generate_cover_letter", label="✍️ 生成求职信",
               sections=["cover_letter", "resume_tips"])
    assert a.id == "generate_cover_letter"
    assert a.sections == ["cover_letter", "resume_tips"]
