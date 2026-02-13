from dataclasses import dataclass


@dataclass(frozen=True)
class PetProfile:
    id: str
    name: str
    editor_title: str
    editor_intro_text: str
    editor_chunks: tuple[str, ...]
    # Chance to start typing random stuff while the prank "Notepad" window is open.
    editor_typing_chance: float = 0.12


PET_PROFILES: dict[str, PetProfile] = {
    "cube": PetProfile(
        id="cube",
        name="CubePet",
        editor_title="annoying_editor.txt - Notepad",
        editor_intro_text=(
            "HEHEHEHA\n\n"
            "ich zieh den editor einfach von der seite rein.\n"
            "du tippst? nein, ich tippe.\n"
        ),
        editor_chunks=(
            "Halllllo ",
            "HEHEHEHA ",
            "lol ",
            "du kannst nix machen ",
            "hehe ",
            "hmmmm ",
        ),
        editor_typing_chance=0.16,
    ),
    "aki": PetProfile(
        id="aki",
        name="Aki",
        editor_title="aki_notes.txt - Notepad",
        editor_intro_text=(
            "Aki\n\n"
            "wenn du ne text datei offen hast...\n"
            "schreib ich random kacke rein.\n"
            "fuetter mich mit daten.\n"
        ),
        editor_chunks=(
            "aki sagt: ",
            "kacke ",
            "hehe ",
            "gib daten ",
            "lol ",
            "du tippst? ich tippe. ",
        ),
        editor_typing_chance=0.25,
    ),
    "pamuk": PetProfile(
        id="pamuk",
        name="Pamuk",
        editor_title="pamuk_devstuff.txt - Notepad",
        editor_intro_text=(
            "PamukDevStuff\n\n"
            "fuettern mit daten.\n"
            "mach mal ne text datei auf.\n"
        ),
        editor_chunks=(
            "pamuk: ",
            "daten pls ",
            "HEHEHEHA ",
            "random ",
            "hmm ",
            "du kannst nix machen ",
        ),
        editor_typing_chance=0.18,
    ),
}
