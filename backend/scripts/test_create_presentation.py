from app.core.tools.builtin.create_presentation import create_presentation

r = create_presentation.invoke(
    {
        "slides_json": '[{"title":"封面"},{"title":"要点","bullets":["A","B"]}]',
        "filename": "demo-deck.pptx",
    }
)
print(r)
