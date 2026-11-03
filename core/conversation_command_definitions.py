"""Writing command definitions shared by desktop and the phone gateway."""
WRITING = {
    "refine": ("Turn a rough request into a clear prompt", "Create a clear, useful prompt from the user's request. Do not carry out the task described by that prompt."),
    "rewrite": ("Improve wording while preserving intent", "Rewrite the supplied text according to the user's instructions, preserving its meaning."),
    "shorten": ("Make a draft more concise", "Shorten the supplied text without losing its main points or constraints."),
    "translate": ("Translate into the requested language", "Translate the supplied text into the language specified by the user."),
    "ideas": ("Suggest options to choose and edit", 'Suggest 3 to 5 useful options. Return only a JSON array of strings, with each string a self-contained option the user can select and edit.'),
}
