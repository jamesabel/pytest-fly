space_block = " "
dot_block = chr(183)  # "·"
# Unicode block characters
right_half_block = chr(9616)  # "▐"
left_half_block = chr(9612)  # "▌"
full_block = chr(9608)  # "█"


def create_text_bar(length: int, start: float, bar: float, force_tick: bool, use_tracer_dots: bool) -> str:
    """
    Create a contiguous horizontal bar that utilizes Unicode left and right half-block characters for twice the resolution of normal characters.

    Args:
        length: Total number of characters in the output string.
        start: Position of the start of the bar, as a portion of the total length (0.0 to 1.0).
        bar: Length of the bar, as a portion of the total length (0.0 to 1.0).
        force_tick: Set to True to always make a "tick" using the start, even if the duration is so short that it would be invisible. If False, the bar will only be shown if the duration is long enough to be visible.
        use_tracer_dots: Set to True to use tracer dots (·) for the padding blocks.

    Returns:
        str: The bar string.
    """

    assert 0.0 <= start <= 1.0
    assert 0.0 <= bar <= 1.0
    assert start + bar <= 1.0

    # create a list of booleans representing the "half blocks"
    transformed_length = 2 * length
    transformed_blocks = []  # False for blank, True for (half) block
    transformed_start = int(round(start * transformed_length))
    transformed_end = int(round((start + bar) * transformed_length))
    for i in range(transformed_length):
        if transformed_start <= i < transformed_end:
            transformed_blocks.append(True)  # bar
        else:
            transformed_blocks.append(False)  # padding (left or right)

    # if requested, ensure there's a least one "tick" visible
    if force_tick and all(not b for b in transformed_blocks) and len(transformed_blocks) > 0:
        tick_position = min(transformed_start, transformed_length - 1)
        transformed_blocks[tick_position] = True

    # taking the transformed blocks two at a time, map on to actual Unicode characters
    bools_to_blocks = {(False, False): space_block, (True, False): left_half_block, (False, True): right_half_block, (True, True): full_block}
    blocks = []
    for i in range(0, transformed_length, 2):
        block = bools_to_blocks[(transformed_blocks[i], transformed_blocks[i + 1])]
        if use_tracer_dots and block == space_block and i % 4 == 0:
            # tracer dots
            block = dot_block
        blocks.append(block)
    bar = "".join(blocks)

    assert len(bar) == length

    return bar


def main():
    width = 16
    for force_tick in [False, True]:
        for left in range(0, width + 1):
            for right in range(left, width + 1):
                start = left / width
                duration = (right - left) / width
                bar = create_text_bar(length=width // 2, start=start, bar=duration, force_tick=force_tick)
                print(f"'{bar}' ({start=:.2f},{duration=:.2f},{len(bar)=},{force_tick=})")


if __name__ == "__main__":
    main()
