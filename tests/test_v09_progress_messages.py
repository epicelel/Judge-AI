from gui_app import progress_message_from_line


def test_progress_message_phases():
    assert progress_message_from_line("Flowing the round...\n") == "Flowing transcript…"
    assert (
        progress_message_from_line("    Technical Circuit run 2/3: AFF 900 out\n")
        == "Judging Technical Circuit 2/3…"
    )
    assert (
        progress_message_from_line("Generating cross-paradigm diff...\n")
        == "Generating cross-paradigm analysis…"
    )
