from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from poker.equity import UNKNOWN_COMBO, hole_combo_label
from poker.filters import hand_table_format
from poker.metrics import when_i_raise as wir
from poker.metrics.base import Metric, register
from poker.metrics.preflop_hand_details import player_cards
from poker.models import Action, Hand, HandDataset
from poker.positions.six_max import position_map


@dataclass
class CallSpot:
    street: str
    player_count: int
    position: str
    size_pct: float
    facing_action: Literal["bet", "raise"]
    aggressor: str
    flop_cards: tuple[str, ...] = ()
    hero_position: str | None = None
    opponent_position: str | None = None


def extract_hero_call_spots(hand: Hand) -> list[CallSpot]:
    """Bind each Hero call to the outstanding opponent aggression on its street."""
    spots: list[CallSpot] = []
    active = set(hand.seat_names.values())
    street: str | None = None
    aggression: Action | None = None
    exact_positions: dict[str, str] | None = None

    for act in hand.actions:
        if act.street != street:
            street = act.street
            aggression = None

        if act.action == "fold":
            active.discard(act.player)
            if aggression is not None and act.player == aggression.player:
                aggression = None
            continue

        if act.action in ("bet", "raise"):
            # Hero's own aggression supersedes the old opponent action too.
            # Intervening opponent calls/checks/posts do not change the actor.
            aggression = act if not act.is_hero and act.player != "Hero" else None
            continue

        if not (act.is_hero and act.player == "Hero" and act.action == "call"):
            continue

        facing = aggression
        # Hero has answered this action; another call needs fresh aggression.
        aggression = None
        if (
            facing is None or facing.pot_before <= 0
            or "Hero" not in active or facing.player not in active
        ):
            continue

        hero_position = opponent_position = None
        if len(active) == 2 and hand_table_format(hand) == "6max":
            if exact_positions is None:
                exact_positions = position_map(hand) if (
                    hand.button_seat in hand.seat_names
                    and len(set(hand.seat_names.values())) == len(hand.seat_names)
                ) else {}
            hero = exact_positions.get("Hero")
            opponent = exact_positions.get(facing.player)
            if hero in wir.EXACT_POSITION_ALL and opponent in wir.EXACT_POSITION_ALL:
                hero_position, opponent_position = hero, opponent

        spots.append(CallSpot(
            street=act.street,
            player_count=len(active),
            position=wir._classify_position(wir._action_order_for_street(hand, act.street, active)),
            size_pct=round(100.0 * facing.amount / facing.pot_before, 4),
            facing_action=facing.action,
            aggressor=facing.player,
            flop_cards=hand.flop_cards if act.street in wir.POSTFLOP_STREETS else (),
            hero_position=hero_position,
            opponent_position=opponent_position,
        ))
    return spots


def _matching_call_spots(hand: Hand, options: dict[str, Any]) -> list[CallSpot]:
    # These WIR helpers only inspect the shared filter fields on a spot.
    # Reusing them keeps size, texture, turn-line and position semantics identical.
    flop_line = wir.classify_flop_to_turn(hand) if wir._truthy(options.get("turn_detail")) else None
    exact = wir._uses_exact_positions(hand, options)
    return [
        spot for spot in extract_hero_call_spots(hand)
        if wir._spot_matches(spot, options, flop_line=flop_line, exact_position_mode=exact)
    ]


def hand_matches_call_options(hand: Hand, options: dict[str, Any] | None) -> bool:
    """Replay uses the same matching spots as the metric, once per hand."""
    return bool(_matching_call_spots(hand, options or {}))


def _revealed_aggressor_combo(hand: Hand, spots: list[CallSpot]) -> str | None:
    if len(set(hand.seat_names.values())) != len(hand.seat_names):
        return None
    # Resolve the actual actors of matching spots, never an arbitrary occupied seat.
    # Active players only leave through folds, so all HU spots share one opponent.
    opponents = {spot.aggressor for spot in spots if spot.player_count == 2}
    if len(opponents) != 1:
        return None
    combo = hole_combo_label(player_cards(hand, next(iter(opponents))))
    return None if combo == UNKNOWN_COMBO else combo


@register
class WhenICallMetric(Metric):
    id = "when_i_call"
    name = "When I Call"
    description = "当 Hero 面对对手下注/加注并跟注时，统计样本及对手亮牌范围"
    chart_type = "stats"

    def compute(self, dataset: HandDataset, options: dict[str, Any] | None = None) -> dict[str, Any]:
        opts = options or {}
        spot_count = hand_count = bet_count = raise_count = 0
        heads_up_grid = wir._as_str_list(opts.get("player_counts")) == ["2"]
        revealed_counts: dict[str, int] = {}

        for hand in dataset.sorted_hands():
            spots = _matching_call_spots(hand, opts)
            if not spots:
                continue
            hand_count += 1
            spot_count += len(spots)
            bet_count += sum(spot.facing_action == "bet" for spot in spots)
            raise_count += sum(spot.facing_action == "raise" for spot in spots)
            if heads_up_grid:
                combo = _revealed_aggressor_combo(hand, spots)
                if combo is not None:
                    revealed_counts[combo] = revealed_counts.get(combo, 0) + 1

        def pct(count: int) -> float | None:
            return round(100.0 * count / spot_count, 2) if spot_count else None

        grid: dict[str, Any] = {"supported": False, "reason": "heads_up_only"}
        if heads_up_grid:
            grid = {
                "supported": True,
                "total_hands": hand_count,
                "revealed_hands": sum(revealed_counts.values()),
                "cells": [
                    {
                        "hand": label,
                        "count": revealed_counts.get(label, 0),
                        "pct": round(100.0 * revealed_counts.get(label, 0) / hand_count, 2)
                        if hand_count else 0.0,
                    }
                    for label in wir.SHOWDOWN_HAND_CLASSES
                ],
            }

        streets = wir._selected_streets(opts)
        flop_detail = wir._truthy(opts.get("flop_detail"))
        turn_detail = wir._truthy(opts.get("turn_detail"))
        return {
            "metric_id": self.id,
            "name": self.name,
            "spot_count": spot_count,
            "hand_count": hand_count,
            "facing_bet": {"count": bet_count, "pct": pct(bet_count)},
            "facing_raise": {"count": raise_count, "pct": pct(raise_count)},
            "opponent_showdown_grid": grid,
            "options": {
                "streets": sorted(streets) if streets is not None else ["ALL"],
                "flop_detail": flop_detail,
                "turn_detail": turn_detail,
                "turn_flop_lines": sorted(wir._parse_turn_detail_lines(opts.get("turn_flop_lines")))
                if turn_detail else [],
                "player_counts": wir._as_str_list(opts.get("player_counts")) or sorted(wir.PLAYER_COUNT_ALL),
                "sizes": wir._as_str_list(opts.get("sizes")) or list(wir.SIZE_IDS),
                "positions": wir._as_str_list(opts.get("positions")) or sorted(wir.POSITION_ALL),
                **{
                    key: wir._as_str_list(opts[key])
                    for key in ("hero_positions", "opponent_positions") if key in opts
                },
                "flop_textures": wir._parse_flop_texture_constraints(opts.get("flop_textures"))
                if flop_detail or turn_detail else {},
            },
        }
