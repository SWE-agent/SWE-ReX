from swerex.runtime.local import split_bash_command


def test_split_bash_command_normal():
    assert split_bash_command("cmd1\ncmd2") == ["cmd1", "cmd2"]


def test_split_bash_command_escaped_newline():
    assert split_bash_command("cmd1\\\n asdf") == ["cmd1\\\n asdf"]


def test_split_bash_command_heredoc():
    assert split_bash_command("cmd1<<EOF\na\nb\nEOF") == ["cmd1<<EOF\na\nb\nEOF"]
    assert split_bash_command("cmd1<<EOF\na\nb\nEOF\ncmd2<<EOF\nd\ne\nEOF") == [
        "cmd1<<EOF\na\nb\nEOF",
        "cmd2<<EOF\nd\ne\nEOF",
    ]


def test_split_bash_command_multiple_commands():
    assert split_bash_command("cmd1\ncmd2\ncmd3") == ["cmd1", "cmd2", "cmd3"]


def test_split_bash_command_multiple_commands_with_linebreaks():
    assert split_bash_command("cmd1\n\ncmd2\n\ncmd3") == ["cmd1", "cmd2", "cmd3"]


def test_split_bash_command_multiple_commands_with_heredocs():
    assert split_bash_command("cmd1<<EOF\na\nb\nEOF\ncmd2<<EOF\nd\ne\nEOF") == [
        "cmd1<<EOF\na\nb\nEOF",
        "cmd2<<EOF\nd\ne\nEOF",
    ]


def test_split_bash_command_multilline_blank_line_heredoc():
    assert split_bash_command("cmd1<<EOF\na\nb\n\n\nEOF\ncmd2<<EOF\nd\ne\nEOF") == [
        "cmd1<<EOF\na\nb\n\n\nEOF",
        "cmd2<<EOF\nd\ne\nEOF",
    ]


def test_split_bash_command_all_blank_lines():
    assert split_bash_command("\n\n\n") == []


def test_split_bash_command_quotation_marks():
    assert split_bash_command('cmd1 "a\nb"') == [
        'cmd1 "a\nb"',
    ]
    assert split_bash_command("cmd1 'a\nb'") == [
        "cmd1 'a\nb'",
    ]


def test_split_command_with_heredoc_quotations():
    assert split_bash_command('cmd1 <<EOF\n"a\nb"\nEOF') == [
        'cmd1 <<EOF\n"a\nb"\nEOF',
    ]
    assert split_bash_command("cmd1 <<EOF\n'a\nb'\nEOF") == [
        "cmd1 <<EOF\n'a\nb'\nEOF",
    ]
