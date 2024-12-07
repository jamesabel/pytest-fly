from functools import cache

from ismain import is_main

try:
    from ..preferences import get_pref
except ImportError:
    get_pref = lambda: None

blocks_characters = [" ", "▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]


def get_full_block() -> str:
    """
    Get the full Unicode block character.
    """
    return blocks_characters[-1]


@cache
def _get_slices_per_block() -> int:
    """
    Get the number of Unicode characters per block (only for textual implementation).
    When the user changes the number of Unicode characters per block, the application needs to be restarted for the change to take effect.
    """
    if (preferences := get_pref()) is None:
        slices = 1
    else:
        slices = int(preferences.textual_slices_per_block)
    if slices < 1:
        slices = 1
    elif slices > 8:
        slices = 8
    return slices


@cache
def _get_blocks(slices_per_block: int) -> list[str]:
    """
    Get the Unicode block characters based on the number of slices per block.
    :param slices_per_block: The number of Unicode characters per block (must be a power of 2).
    """
    # target font: Cascadia Mono
    slices_per_block = 2 ** (slices_per_block.bit_length() - 1)  # ensure slices_per_block is a power of 2

    if slices_per_block > len(blocks_characters) - 1:
        slices_per_block = len(blocks_characters) - 1
    skip = int((len(blocks_characters) - 1) / slices_per_block)  # how many block characters to skip based on the number of slices per block
    blocks = []
    for i in range(0, (slices_per_block + 1) * skip, skip):
        blocks.append(blocks_characters[i])
    return blocks


def block_fraction_to_unicode(fraction: float, force_thinnest_block=False, slices_per_block: int = None) -> str:
    """
    Convert a fraction to a Unicode block character.
    :param fraction: A fraction between 0 and 1.
    :param force_thinnest_block: If True, the thinnest block will be used for the fraction 0. (default: False)
    :param slices_per_block: The number of Unicode characters per block (must be a power of 2). If None, the value will be obtained from the preferences. (default: None)
    """

    if slices_per_block is None:
        slices_per_block = _get_slices_per_block()
    blocks = _get_blocks(slices_per_block)
    index = int(round(fraction * (len(blocks) - 1)))
    if index == 0 and force_thinnest_block:
        index = 1
    block = blocks[index]
    return block


def main():
    """
    Test the block_fraction_to_unicode function.
    """

    test_points = 16
    for force_thinnest_block in [False, True]:
        for slices_per_block in [1, 2, 4, 8]:
            print(f"{force_thinnest_block=}, {slices_per_block=}")
            for i in range(test_points + 1):
                value = i / test_points
                character = block_fraction_to_unicode(value, force_thinnest_block, slices_per_block)
                print(f"{value:.3f},{character=}")
            print()


if is_main():
    main()
