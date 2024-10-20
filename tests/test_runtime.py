import pytest

from swerex.runtime.abstract import BashIncorrectSyntaxError
from swerex.runtime.local import _check_bash_command, _split_bash_command


def test_split_bash_command_normal():
    assert _split_bash_command("cmd1\ncmd2") == ["cmd1", "cmd2"]


def test_split_bash_command_escaped_newline():
    assert _split_bash_command("cmd1\\\n asdf") == ["cmd1\\\n asdf"]


def test_split_bash_command_heredoc():
    assert _split_bash_command("cmd1<<EOF\na\nb\nEOF") == ["cmd1<<EOF\na\nb\nEOF"]
    assert _split_bash_command("cmd1<<EOF\na\nb\nEOF\ncmd2<<EOF\nd\ne\nEOF") == [
        "cmd1<<EOF\na\nb\nEOF",
        "cmd2<<EOF\nd\ne\nEOF",
    ]


def test_split_bash_command_multiple_commands():
    assert _split_bash_command("cmd1\ncmd2\ncmd3") == ["cmd1", "cmd2", "cmd3"]


def test_split_bash_command_multiple_commands_with_linebreaks():
    assert _split_bash_command("cmd1\n\ncmd2\n\ncmd3") == ["cmd1", "cmd2", "cmd3"]


def test_split_bash_command_multiple_commands_with_heredocs():
    assert _split_bash_command("cmd1<<EOF\na\nb\nEOF\ncmd2<<EOF\nd\ne\nEOF") == [
        "cmd1<<EOF\na\nb\nEOF",
        "cmd2<<EOF\nd\ne\nEOF",
    ]


def test_split_bash_command_multilline_blank_line_heredoc():
    assert _split_bash_command("cmd1<<EOF\na\nb\n\n\nEOF\ncmd2<<EOF\nd\ne\nEOF") == [
        "cmd1<<EOF\na\nb\n\n\nEOF",
        "cmd2<<EOF\nd\ne\nEOF",
    ]


def test_split_bash_command_all_blank_lines():
    assert _split_bash_command("\n\n\n") == []


def test_split_bash_command_quotation_marks():
    assert _split_bash_command('cmd1 "a\nb"') == [
        'cmd1 "a\nb"',
    ]
    assert _split_bash_command("cmd1 'a\nb'") == [
        "cmd1 'a\nb'",
    ]


def test_split_command_with_heredoc_quotations():
    assert _split_bash_command('cmd1 <<EOF\n"a\nb"\nEOF') == [
        'cmd1 <<EOF\n"a\nb"\nEOF',
    ]
    assert _split_bash_command("cmd1 <<EOF\n'a\nb'\nEOF") == [
        "cmd1 <<EOF\n'a\nb'\nEOF",
    ]


def test_check_bash_command_invalid():
    with pytest.raises(BashIncorrectSyntaxError):
        _check_bash_command("(a")
    with pytest.raises(BashIncorrectSyntaxError):
        _check_bash_command("a='")
    with pytest.raises(BashIncorrectSyntaxError):
        _check_bash_command("for")


def test_check_bash_command_valid():
    _check_bash_command("(a)")
    _check_bash_command("a=''")
