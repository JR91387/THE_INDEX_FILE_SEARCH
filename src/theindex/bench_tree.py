# SPDX-License-Identifier: MIT
"""A seeded synthetic folder tree for `the-index bench`: same seed and size, same tree, on any machine.

Shape: folders hold ~20 files, nested up to 7 levels with fan-out 6; ~3 % of files are documents with real titles
and front matter; a few cache folders (`node_modules`, `.git`) hold many small files. Sizes are set with truncate,
so most files take no disk blocks."""
import os
import random
from pathlib import Path

_WORD_TEXT = ("alpha amber atlas audit autumn badge basin beacon birch budget cabin canyon cedar census chart cinder "
            "clover cobalt comet compass copper coral cotton crane crystal delta desert draft ember engine estate "
            "falcon fern field fjord forest garden garnet glacier granite harbor harvest hazel horizon indigo inlet "
            "invoice iris island ivory jasper journal juniper kernel lagoon lantern ledger lemon linen lotus maple "
            "marble meadow memo mesa meteor minute mosaic nectar nickel north oasis ocean olive onyx orbit orchid "
            "pebble pepper pilot pine planet plaza prairie quartz quill radar raven report ridge river saffron "
            "salmon sierra signal silver sketch slate solar spruce summit tango thistle timber topaz tundra "
            "umber valley velvet vertex violet walnut willow winter yarrow zephyr zinc")
WORDS = _WORD_TEXT.split()
PLAIN = (".txt", ".log", ".csv", ".json", ".py", ".js", ".jpg", ".png", ".mp3", ".zip", ".bin", ".cfg")
DOCS = (".md", ".html")
FILES_PER_DIR, FAN_OUT, MAX_DEPTH = 20, 6, 7


def _name(rng, ext):
    words = rng.sample(WORDS, rng.choice((1, 2, 2, 3)))
    return "_".join(words) + (f"_{rng.randrange(1000)}" if rng.random() < 0.4 else "") + ext


def _doc_text(rng, ext):
    title = " ".join(w.capitalize() for w in rng.sample(WORDS, 3))
    tags = ", ".join(rng.sample(WORDS, 2))
    if ext == ".md":
        return f"---\ntitle: {title}\nauthor: Alice {rng.choice(WORDS).capitalize()}\ntags: [{tags}]\n---\n# {title}\n"
    return f"<html lang=en><head><title>{title}</title><meta name=keywords content=\"{tags}\"></head></html>\n"


def _dir_paths(root, count, rng):
    """`count` folder paths below root, breadth first, fan-out FAN_OUT, at most MAX_DEPTH deep."""
    out, queue, head = [root], [root], 0
    while len(out) < count and head < len(queue):
        parent, head = queue[head], head + 1
        for child in [parent / _name(rng, "") for _ in range(min(FAN_OUT, count - len(out)))]:
            out.append(child)
            if len(child.relative_to(root).parts) < MAX_DEPTH:
                queue.append(child)
    return out


def _fill(folder, rng, files):
    folder.mkdir(parents=True, exist_ok=True)
    for _ in range(files):
        is_doc = rng.random() < 0.03
        ext = rng.choice(DOCS) if is_doc else rng.choice(PLAIN)
        path = folder / _name(rng, ext)
        while path.exists():                  # names repeat now and then: keep the file count exact
            path = folder / _name(rng, ext)
        if is_doc:
            path.write_text(_doc_text(rng, ext), encoding="utf-8")
        else:
            with open(path, "wb") as fh:
                fh.truncate(int(rng.paretovariate(1.2) * 600))


def make(root, files=1_000_000, seed=7):
    """Build the tree under root (which must not exist or be empty). Returns (files, folders) written."""
    root = Path(root)
    rng = random.Random(seed)
    cache_files = files // 50
    dirs = _dir_paths(root, max(1, (files - cache_files) // FILES_PER_DIR), rng)
    for folder in dirs:
        _fill(folder, rng, FILES_PER_DIR)
    for i in range(max(1, cache_files // 500)):
        _fill(dirs[(i * 97) % len(dirs)] / "node_modules" / f"pkg{i}", rng, 500)
    written = len(dirs) * FILES_PER_DIR + max(1, cache_files // 500) * 500
    return written, len(dirs)


def change(root, fraction=0.01, seed=11):
    """Touch `fraction` of folders: one file added, one renamed in each. Returns folders changed."""
    rng = random.Random(seed)
    folders = sorted(p for p, _, _ in os.walk(root) if "node_modules" not in p)
    picked = rng.sample(folders, max(1, int(len(folders) * fraction)))
    for folder in picked:
        _fill(Path(folder), rng, 1)
        names = sorted(n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n)))
        if names:
            os.replace(os.path.join(folder, names[0]), os.path.join(folder, "renamed_" + names[0]))
    return len(picked)


def reference_walk(root):
    """A bare scandir + stat walk of the tree: the floor any scanner is measured against. Returns files seen."""
    seen, stack = 0, [str(root)]
    while stack:
        with os.scandir(stack.pop()) as it:
            entries = list(it)
        stack += [e.path for e in entries if e.is_dir(follow_symlinks=False)]
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                entry.stat(follow_symlinks=False)
                seen += 1
    return seen
