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


HeroResponse = Literal["fold", "call", "raise", "check", "bet"]


@dataclass
class CallDecisionSpot:
    street: str
    player_count: int
    position: str
    facing_kind: Literal["aggression", "check"]
    size_pct: float | None
    hero_response: HeroResponse
    aggressor: str
    facing_action: Literal["bet", "raise", "check"]
    flop_cards: tuple[str, ...] = ()
    hero_position: str | None = None
    opponent_position: str | None = None


def _is_hero(act: Action) -> bool:
    return act.is_hero or act.player == "Hero"


def hand_allowed_for_when_i_call(hand: Hand, options: dict[str, Any]) -> bool:
    """Keep postflop hands where Hero is not the final preflop aggressor."""
    context = wir.classify_preflop_aggressor_context(hand)
    if (
        context.final_aggressor is None
        or context.hero_is_final_aggressor
        or context.pot_type not in wir._selected_pot_types(options)
    ):
        return False
    if any(
        act.street == "preflop" and _is_hero(act) and act.action == "fold"
        for act in hand.actions
    ):
        return False
    return (
        hand.went_to_flop
        or len(hand.flop_cards) >= 3
        or any(act.street in wir.POSTFLOP_STREETS for act in hand.actions)
    )


def _aggression_decision_spot(
    hand: Hand,
    response: HeroResponse,
    facing: Action,
    active: set[str],
    exact_positions: dict[str, str] | None,
) -> CallDecisionSpot | None:
    if (
        facing.pot_before <= 0
        or "Hero" not in active
        or facing.player not in active
        or facing.player == "Hero"
    ):
        return None

    hero_position = opponent_position = None
    if len(active) == 2 and hand_table_format(hand) == "6max":
        positions = exact_positions or {}
        hero = positions.get("Hero")
        opponent = positions.get(facing.player)
        if hero in wir.EXACT_POSITION_ALL and opponent in wir.EXACT_POSITION_ALL:
            hero_position, opponent_position = hero, opponent

    return CallDecisionSpot(
        street=facing.street,
        player_count=len(active),
        position=wir._classify_position(wir._action_order_for_street(hand, facing.street, active)),
        facing_kind="aggression",
        size_pct=round(100.0 * facing.amount / facing.pot_before, 4),
        hero_response=response,
        aggressor=facing.player,
        facing_action="raise" if facing.action == "raise" else "bet",
        flop_cards=hand.flop_cards,
        hero_position=hero_position,
        opponent_position=opponent_position,
    )


def _check_decision_spot(
    hand: Hand,
    response: Literal["check", "bet"],
    checker: Action,
    active: set[str],
    exact_positions: dict[str, str] | None,
) -> CallDecisionSpot | None:
    if "Hero" not in active or checker.player not in active or checker.player == "Hero":
        return None

    hero_position = opponent_position = None
    if len(active) == 2 and hand_table_format(hand) == "6max":
        positions = exact_positions or {}
        hero = positions.get("Hero")
        opponent = positions.get(checker.player)
        if hero in wir.EXACT_POSITION_ALL and opponent in wir.EXACT_POSITION_ALL:
            hero_position, opponent_position = hero, opponent

    return CallDecisionSpot(
        street=checker.street,
        player_count=len(active),
        position=wir._classify_position(wir._action_order_for_street(hand, checker.street, active)),
        facing_kind="check",
        size_pct=None,
        hero_response=response,
        aggressor=checker.player,
        facing_action="check",
        flop_cards=hand.flop_cards,
        hero_position=hero_position,
        opponent_position=opponent_position,
    )


def extract_hero_call_decision_spots(hand: Hand) -> list[CallDecisionSpot]:
    """Extract ordered opponent-action -> Hero-response decisions postflop.

    Passive opponent actions leave the latest aggression outstanding, while a
    newer raise replaces it. A street where Hero leads before facing opponent
    aggression is a donk line and produces no WIC spots on that street.
    """
    spots: list[CallDecisionSpot] = []
    active = set(hand.seat_names.values())
    street: str | None = None
    outstanding: Action | None = None
    checked_by: list[Action] = []
    saw_opponent_aggression = False
    donk_line = False
    exact_positions: dict[str, str] | None = None
    if hand_table_format(hand) == "6max":
        exact_positions = position_map(hand) if (
            hand.button_seat in hand.seat_names
            and len(set(hand.seat_names.values())) == len(hand.seat_names)
        ) else {}

    for act in hand.actions:
        if act.street != street:
            street = act.street
            outstanding = None
            checked_by = []
            saw_opponent_aggression = False
            donk_line = False

        if act.street not in wir.POSTFLOP_STREETS:
            if act.action == "fold":
                active.discard(act.player)
            continue

        hero_action = _is_hero(act)

        if hero_action and act.action in ("bet", "raise"):
            if outstanding is not None and not donk_line:
                spot = _aggression_decision_spot(hand, "raise", outstanding, active, exact_positions)
                if spot is not None:
                    spots.append(spot)
                outstanding = None
            elif checked_by and not donk_line:
                spot = _check_decision_spot(hand, "bet", checked_by[-1], active, exact_positions)
                if spot is not None:
                    spots.append(spot)
            elif not saw_opponent_aggression:
                donk_line = True
                outstanding = None
            checked_by = []
            continue

        if not hero_action and act.action in ("bet", "raise"):
            saw_opponent_aggression = True
            checked_by = []
            outstanding = None if donk_line else act
            continue

        if hero_action and act.action == "check":
            if outstanding is None and checked_by and not donk_line:
                spot = _check_decision_spot(hand, "check", checked_by[-1], active, exact_positions)
                if spot is not None:
                    spots.append(spot)
            checked_by = []
            continue

        if not hero_action and act.action == "check":
            if outstanding is None and not donk_line:
                checked_by.append(act)
            continue

        if hero_action and act.action in ("fold", "call"):
            if outstanding is not None and not donk_line:
                response: HeroResponse = "fold" if act.action == "fold" else "call"
                spot = _aggression_decision_spot(hand, response, outstanding, active, exact_positions)
                if spot is not None:
                    spots.append(spot)
            outstanding = None
            checked_by = []
            if act.action == "fold":
                active.discard(act.player)
            continue

        if act.action == "fold":
            active.discard(act.player)
            if outstanding is not None and outstanding.player == act.player:
                outstanding = None

    return spots


# Compatibility for internal code that imported the former extractor name.
extract_hero_call_spots = extract_hero_call_decision_spots


def classify_wic_flop_to_turn(hand: Hand) -> str | None:
    """Classify Hero's final relevant flop response before the turn."""
    if not wir._hand_reached_turn(hand):
        return None
    flop_actions = wir._flop_betting_actions(hand)
    aggressive = [act for act in flop_actions if act.action in ("bet", "raise")]
    if not aggressive:
        return "flop_checkcheck" if flop_actions and all(
            act.action in ("check", "fold") for act in flop_actions
        ) else None
    if _is_hero(aggressive[0]):
        return None
    flop_spots = [spot for spot in extract_hero_call_decision_spots(hand) if spot.street == "flop"]
    if not flop_spots:
        return None
    response = flop_spots[-1].hero_response
    if response == "call":
        return "flop_call"
    if response == "raise":
        return "flop_raise"
    return None


def _matching_decision_spots(hand: Hand, options: dict[str, Any]) -> list[CallDecisionSpot]:
    if not hand_allowed_for_when_i_call(hand, options):
        return []
    flop_line = classify_wic_flop_to_turn(hand) if wir._truthy(options.get("turn_detail")) else None
    exact = wir._uses_exact_positions(hand, options)
    return [
        spot for spot in extract_hero_call_decision_spots(hand)
        if wir._spot_matches(spot, options, flop_line=flop_line, exact_position_mode=exact)
    ]


def hand_matches_call_options(hand: Hand, options: dict[str, Any] | None) -> bool:
    """Replay uses the exact same eligible matching spots as the metric."""
    opts = options or {}
    replay_outcome = opts.get("replay_outcome")
    responses = {
        "hero_fold": "fold", "hero_call": "call", "hero_raise": "raise",
        "hero_check": "check", "hero_bet": "bet",
    }
    if replay_outcome is not None and replay_outcome not in responses:
        return False
    spots = _matching_decision_spots(hand, opts)
    if replay_outcome is None:
        return bool(spots)
    return any(spot.hero_response == responses[replay_outcome] for spot in spots)


def _revealed_aggressor_combo(hand: Hand, spots: list[CallDecisionSpot]) -> str | None:
    if len(set(hand.seat_names.values())) != len(hand.seat_names):
        return None
    opponents = {spot.aggressor for spot in spots if spot.player_count == 2}
    if len(opponents) != 1:
        return None
    combo = hole_combo_label(player_cards(hand, next(iter(opponents))))
    return None if combo == UNKNOWN_COMBO else combo


@register
class WhenICallMetric(Metric):
    """Hero decisions after ordered opponent postflop actions in non-PFA hands."""

    id = "when_i_call"
    name = "When I Call"
    description = "Hero 作为翻前非最终进攻者进入 Flop 后，面对对手进攻或过牌时的响应频率"
    chart_type = "stats"

    def compute(self, dataset: HandDataset, options: dict[str, Any] | None = None) -> dict[str, Any]:
        opts = options or {}
        spots: list[CallDecisionSpot] = []
        hand_count = 0
        heads_up_grid = wir._as_str_list(opts.get("player_counts")) == ["2"]
        revealed_counts: dict[str, int] = {}

        for hand in dataset.sorted_hands():
            hand_spots = _matching_decision_spots(hand, opts)
            if not hand_spots:
                continue
            hand_count += 1
            spots.extend(hand_spots)
            if heads_up_grid:
                combo = _revealed_aggressor_combo(hand, hand_spots)
                if combo is not None:
                    revealed_counts[combo] = revealed_counts.get(combo, 0) + 1

        spot_count = len(spots)

        aggression_spots = [spot for spot in spots if spot.facing_kind == "aggression"]
        check_spots = [spot for spot in spots if spot.facing_kind == "check"]

        def outcome(
            response: HeroResponse,
            group: list[CallDecisionSpot],
        ) -> dict[str, int | float | None]:
            count = sum(spot.hero_response == response for spot in group)
            pct = round(100.0 * count / len(group), 2) if group else None
            return {"count": count, "pct": pct}

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
            "hero_fold": outcome("fold", aggression_spots),
            "hero_call": outcome("call", aggression_spots),
            "hero_raise": outcome("raise", aggression_spots),
            "hero_check": outcome("check", check_spots),
            "hero_bet": outcome("bet", check_spots),
            "opponent_showdown_grid": grid,
            "options": {
                "pot_types": [key for key in wir.POT_TYPE_IDS if key in wir._selected_pot_types(opts)],
                "streets": sorted(streets & wir.POSTFLOP_STREETS) if streets is not None else ["ALL"],
                "flop_detail": flop_detail,
                "turn_detail": turn_detail,
                "turn_flop_lines": sorted(wir._parse_turn_detail_lines(opts.get("turn_flop_lines")))
                if turn_detail else [],
                "player_counts": wir._as_str_list(opts.get("player_counts")) or sorted(wir.PLAYER_COUNT_ALL),
                "sizes": wir._as_str_list(opts.get("sizes")) if "sizes" in opts else list(wir.SIZE_IDS),
                "positions": wir._as_str_list(opts.get("positions")) or sorted(wir.POSITION_ALL),
                **{key: wir._as_str_list(opts[key])
                   for key in ("hero_positions", "opponent_positions") if key in opts},
                "flop_textures": wir._parse_flop_texture_constraints(opts.get("flop_textures"))
                if flop_detail or turn_detail else {},
            },
        }
