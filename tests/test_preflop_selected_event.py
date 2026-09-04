from __future__ import annotations

import unittest

from poker.models import HandDataset
from poker.replay.service import get_replay
from tests.test_preflop_actor_hand_details import act, make_hand, metric_for, raise_to


class PreflopSelectedEventTests(unittest.TestCase):
    def _threebet_dataset(self, table_format: str) -> HandDataset:
        names = {
            "HJ": "Opener",
            "CO": "Hero",
            "BTN": "Cold Fourbettor",
            "SB": "Small",
            "BB": "Big",
        }
        return HandDataset(
            [
                make_hand(
                    f"{table_format}-opener-call",
                    table_format,
                    names,
                    [raise_to("Opener", 2.5), raise_to("Hero", 8), act("Opener", "call")],
                    {"Opener": ("Ah", "Kd")},
                    site="ggpoker",
                ),
                make_hand(
                    f"{table_format}-opener-fourbet",
                    table_format,
                    names,
                    [
                        raise_to("Opener", 2.5),
                        raise_to("Hero", 8),
                        raise_to("Opener", 22),
                    ],
                    {"Opener": ("Qc", "Qd")},
                    site="coinpoker",
                ),
                make_hand(
                    f"{table_format}-all-fold",
                    table_format,
                    names,
                    [
                        raise_to("Opener", 2.5),
                        raise_to("Hero", 8),
                        act("Cold Fourbettor", "fold"),
                        act("Small", "fold"),
                        act("Big", "fold"),
                        act("Opener", "fold"),
                    ],
                    site="ggpoker",
                ),
                make_hand(
                    f"{table_format}-cold-fourbet",
                    table_format,
                    names,
                    [
                        raise_to("Opener", 2.5),
                        raise_to("Hero", 8),
                        raise_to("Cold Fourbettor", 22),
                        act("Opener", "fold"),
                    ],
                    {"Cold Fourbettor": ("As", "5s")},
                    site="coinpoker",
                ),
            ]
        )

    def test_event_counts_and_replay_subsets_match_for_6max_and_9max(self) -> None:
        expected_ids = {
            "opener_call": "opener-call",
            "opener_4bet": "opener-fourbet",
            "all_fold": "all-fold",
            "cold_4bet": "cold-fourbet",
        }
        for table_format in ("6max", "9max"):
            with self.subTest(table_format=table_format):
                dataset = self._threebet_dataset(table_format)
                options = {
                    "action": "3bet",
                    "hero_position": "CO",
                    "opener_position": "HJ",
                    "table_format": table_format,
                }
                result = metric_for(table_format).compute(dataset, options)

                self.assertEqual(result["spot_count"], 4)
                self.assertEqual(
                    result["event_counts"],
                    {
                        "opener_responded": 3,
                        "opener_fold": 1,
                        "opener_call": 1,
                        "opener_4bet": 1,
                        "all_fold": 1,
                        "cold_4bet": 1,
                    },
                )
                for event_key, suffix in expected_ids.items():
                    replay = get_replay(
                        dataset,
                        f"preflop_analysis{'_9max' if table_format == '9max' else ''}",
                        0,
                        {**options, "selected_event": event_key},
                    )
                    self.assertEqual(replay["total"], result["event_counts"][event_key])
                    self.assertEqual(replay["hand"]["hand_id"], f"{table_format}-{suffix}")

                # Clearing selected_event restores the entire base spot. Switching
                # keys changes the subset without changing any base-spot options.
                reset = get_replay(
                    dataset,
                    f"preflop_analysis{'_9max' if table_format == '9max' else ''}",
                    0,
                    {**options, "selected_event": ""},
                )
                switched = get_replay(
                    dataset,
                    f"preflop_analysis{'_9max' if table_format == '9max' else ''}",
                    0,
                    {**options, "selected_event": "opener_call"},
                )
                self.assertEqual(reset["total"], 4)
                self.assertEqual(switched["total"], 1)
                self.assertEqual(switched["hand"]["hand_id"], f"{table_format}-opener-call")

                # A non-actor event remains a valid replay filter but does not
                # acquire a misleading opponent-card detail table.
                self.assertNotIn("all_fold", result["hand_details"])

    def test_open_faced_3bet_replay_keeps_cold_caller_in_full_hand(self) -> None:
        for table_format in ("6max", "9max"):
            with self.subTest(table_format=table_format):
                names = {"CO": "Hero", "BTN": "Threebettor", "SB": "Cold Caller"}
                hand = make_hand(
                    f"{table_format}-faced-threebet-multiway",
                    table_format,
                    names,
                    [
                        raise_to("Hero", 2.5),
                        raise_to("Threebettor", 8),
                        act("Cold Caller", "call"),
                        act("Hero", "call"),
                    ],
                    {
                        "Threebettor": ("As", "Ad"),
                        "Cold Caller": ("Kh", "Kd"),
                    },
                )
                dataset = HandDataset([hand])
                options = {
                    "action": "open_raise",
                    "hero_position": "CO",
                    "selected_event": "faced_3bet",
                    "table_format": table_format,
                }
                result = metric_for(table_format).compute(dataset, options)
                replay = get_replay(
                    dataset,
                    f"preflop_analysis{'_9max' if table_format == '9max' else ''}",
                    0,
                    options,
                )

                self.assertEqual(result["event_counts"]["faced_3bet"], 1)
                self.assertEqual(replay["total"], 1)
                self.assertIn("Cold Caller", {player["name"] for player in replay["hand"]["players"]})
                self.assertTrue(
                    any(
                        frame["actor"] == "Cold Caller" and frame["action"] == "call"
                        for frame in replay["hand"]["frames"]
                    )
                )
                self.assertEqual(
                    result["hand_details"]["faced_3bet"]["hands"],
                    [{"hand": "AA", "count": 1, "pct": 100.0}],
                )

    def test_unknown_selected_event_fails_closed(self) -> None:
        dataset = self._threebet_dataset("6max")
        replay = get_replay(
            dataset,
            "preflop_analysis",
            0,
            {
                "action": "3bet",
                "hero_position": "CO",
                "opener_position": "HJ",
                "selected_event": "not-a-real-event",
            },
        )
        self.assertEqual(replay, {"index": 0, "total": 0, "hand": None})

    def test_existing_3bet_and_4bet_matrices_remain_available(self) -> None:
        for table_format in ("6max", "9max"):
            with self.subTest(table_format=table_format):
                dataset = self._threebet_dataset(table_format)
                names = {"HJ": "Opener", "CO": "Threebettor", "BTN": "Hero"}
                dataset.hands.append(
                    make_hand(
                        f"{table_format}-matrix-fourbet-call",
                        table_format,
                        names,
                        [
                            raise_to("Opener", 2.5),
                            raise_to("Threebettor", 8),
                            raise_to("Hero", 22),
                            act("Threebettor", "call"),
                        ],
                        {"Threebettor": ("Ac", "Kc")},
                    )
                )

                threebet_matrix = metric_for(table_format).compute(
                    dataset,
                    {"action": "3bet_matrix"},
                )
                threebet_cell = next(
                    cell
                    for cell in threebet_matrix["cells"]
                    if cell.get("threebettor") == "CO" and cell.get("opener") == "HJ"
                )
                self.assertEqual(threebet_matrix["spot_count"], 5)
                self.assertTrue(threebet_cell["valid"])
                self.assertEqual(threebet_cell["call"]["count"], 1)
                self.assertEqual(threebet_cell["fourbet"]["count"], 1)

                fourbet_matrix = metric_for(table_format).compute(
                    dataset,
                    {"action": "4bet_matrix"},
                )
                fourbet_cell = next(
                    cell
                    for cell in fourbet_matrix["cells"]
                    if cell.get("fourbettor") == "BTN" and cell.get("threebettor") == "CO"
                )
                self.assertEqual(fourbet_matrix["spot_count"], 3)
                self.assertTrue(fourbet_cell["valid"])
                self.assertEqual(fourbet_cell["call"]["count"], 1)
                self.assertEqual(fourbet_cell["call_hands"][0]["hand"], "AKs")


if __name__ == "__main__":
    unittest.main()
