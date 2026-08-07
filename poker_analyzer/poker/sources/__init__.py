from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from poker.models import Hand, HandDataset
from poker.parser import parse_file, parse_text


class DataSource(ABC):
    """Abstract hand history source.

    Local directory now; upload / drag-drop can implement the same interface later.
    """

    @abstractmethod
    def load(self) -> HandDataset:
        raise NotImplementedError


class LocalDirectorySource(DataSource):
    def __init__(self, directory: Path | str, pattern: str = "*.txt") -> None:
        self.directory = Path(directory)
        self.pattern = pattern

    def load(self) -> HandDataset:
        if not self.directory.exists():
            raise FileNotFoundError(f"Data directory not found: {self.directory}")

        hands: list[Hand] = []
        files = sorted(self.directory.glob(self.pattern))
        for path in files:
            if not path.is_file():
                continue
            hands.extend(parse_file(path))

        # Deduplicate by hand_id (same hand may appear if files overlap)
        unique: dict[str, Hand] = {}
        for hand in hands:
            unique[hand.hand_id] = hand

        dataset = HandDataset(
            hands=list(unique.values()),
            source_label=f"local:{self.directory.resolve()}",
        )
        dataset.hands = dataset.sorted_hands()
        return dataset


class TextUploadSource(DataSource):
    """Future-ready source for browser file uploads."""

    def __init__(self, files: list[tuple[str, str]]) -> None:
        """
        files: list of (filename, text_content)
        """
        self.files = files

    def load(self) -> HandDataset:
        hands: list[Hand] = []
        for name, text in self.files:
            hands.extend(parse_text(text, source_file=name))

        unique: dict[str, Hand] = {}
        for hand in hands:
            unique[hand.hand_id] = hand

        dataset = HandDataset(hands=list(unique.values()), source_label="upload")
        dataset.hands = dataset.sorted_hands()
        return dataset
