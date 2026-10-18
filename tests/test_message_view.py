from wechat_work_recorder.message_view import split_messages, message_for_line


def test_message_numbers_preserve_original_lines_with_date_before_nickname():
    text = '2026/10/12 09:00\n测试昵称甲\n8393--6*4\n2026/10/12 10:00\n测试昵称乙\n计时3（贴标）'
    blocks = split_messages(text, ['一群'])
    assert [(block.number, block.start_line, block.end_line, block.nickname) for block in blocks] == [
        (1, 1, 3, '测试昵称甲'), (2, 4, 6, '测试昵称乙')]
    assert message_for_line(blocks, 3) == 1
    assert message_for_line(blocks, 6) == 2
    assert blocks[1].raw_text == '2026/10/12 10:00\n测试昵称乙\n计时3（贴标）'
