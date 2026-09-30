"""`tapesmith inv`: Boxen mit Inhalt, Verleihliste und Label-Druck.

Zentrale Nummernkreise: `label box` holt den Zähler für die Vorlage `aufbewahrungsbox`
ausschließlich über `numbering.counter_store(ctx.load_config())`, nie einen lokalen Default.
"""

import argparse
from datetime import datetime

from tapesmith import numbering
from tapesmith.cli_cmds.base import CliContext, add_print_options, positive_int
from tapesmith.inventory import InventoryStore, contents_lines, loan_lines, render_box_label, render_lines_label
from tapesmith.tape.profiles import current_tape
from tapesmith.i18n import N_, _t

COMMAND = "inv"
HELP = N_("Inventarlisten: Boxen mit Inhalt und Verleihliste")

_DATE_FMT = "%d.%m.%Y"


def register(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="inv_cmd", required=True)

    box = sub.add_parser("box", help=_t("Boxen verwalten"))
    box_sub = box.add_subparsers(dest="box_cmd", required=True)
    ba = box_sub.add_parser("add", help=_t("Box anlegen"))
    ba.add_argument("id")
    ba.add_argument("ort")
    ba.add_argument("--note", default="")
    box_sub.add_parser("list", help=_t("Boxen auflisten"))
    bs = box_sub.add_parser("show", help=_t("Box mit Inhalt anzeigen"))
    bs.add_argument("id")
    br = box_sub.add_parser("rm", help=_t("Box löschen (muss leer sein)"))
    br.add_argument("id")

    a = sub.add_parser("add", help=_t("Gegenstand hinzufügen"))
    a.add_argument("name")
    a.add_argument("--box", dest="box_id", metavar="ID", help=_t("Box, in die der Gegenstand kommt"))
    a.add_argument("--qty", type=positive_int, default=1, help=_t("Anzahl"))
    a.add_argument("--note", default="")

    r = sub.add_parser("rm", help=_t("Gegenstand entfernen"))
    r.add_argument("item_id", type=int, metavar="ITEM_ID")

    m = sub.add_parser("mv", help=_t("Gegenstand in eine andere Box verschieben ('-' = keine Box)"))
    m.add_argument("item_id", type=int, metavar="ITEM_ID")
    m.add_argument("box_id", metavar="ID|-")

    f = sub.add_parser("find", help=_t("Gegenstände und Boxen durchsuchen"))
    f.add_argument("query", nargs="+", metavar=_t("SUCHBEGRIFF"))

    lend = sub.add_parser("lend", help=_t("Gegenstand verleihen"))
    lend.add_argument("item", metavar=_t("GEGENSTAND"))
    lend.add_argument("person", metavar="PERSON")
    lend.add_argument("--due", metavar=_t("TT.MM.JJJJ"), help=_t("Rückgabe bis (optional)"))

    ret = sub.add_parser("return", help=_t("Rückgabe vermerken"))
    ret.add_argument("loan_id", type=int, metavar="LOAN_ID")

    loans = sub.add_parser("loans", help=_t("Verleihliste anzeigen"))
    loans.add_argument("--all", action="store_true", help=_t("auch zurückgegebene Posten zeigen"))

    label = sub.add_parser("label", help=_t("Label drucken"))
    label_sub = label.add_subparsers(dest="label_cmd", required=True)
    lb = label_sub.add_parser("box", help=_t("Box-Label (QR + Nummer + Ort)"))
    lb.add_argument("id")
    add_print_options(lb)
    lc = label_sub.add_parser("content", help=_t("Inhaltslabel (bis 3 Zeilen)"))
    lc.add_argument("id")
    add_print_options(lc)
    ll = label_sub.add_parser("loan", help=_t("Verleih-Label"))
    ll.add_argument("loan_id", type=int, metavar="LOAN_ID")
    add_print_options(ll)


def _parse_due(text: str | None):
    if not text:
        return None
    try:
        return datetime.strptime(text, _DATE_FMT).date()
    except ValueError as exc:
        raise ValueError(_t("Datum '{text}' nicht lesbar (TT.MM.JJJJ)", text=text)) from exc


def _box_line(box) -> str:
    marker = f" ({box.note})" if box.note else ""
    return f"{box.id:<12} {box.location}{marker}"


def _item_line(item) -> str:
    qty = f" ×{item.qty}" if item.qty != 1 else ""
    note = f" ({item.note})" if item.note else ""
    return f"  #{item.id:<4} {item.name}{qty}{note}"


def _loan_line(loan, today) -> str:
    text = _t("#{id:<4} {item} → {person} seit {since:%d.%m.%Y}", id=loan.id, item=loan.item, person=loan.person, since=loan.since)
    if loan.due is not None:
        text += _t(" · bis {due:%d.%m.%Y}", due=loan.due)
    if loan.overdue(today):
        text += _t(" (überfällig)")
    if loan.returned is not None:
        text += _t(" · zurück am {returned:%d.%m.%Y}", returned=loan.returned)
    return text


def run(args: argparse.Namespace, ctx: CliContext) -> int:
    with InventoryStore() as store:
        if args.inv_cmd == "box":
            return _run_box(args, ctx, store)
        if args.inv_cmd == "add":
            try:
                item = store.add_item(args.name, box_id=args.box_id, qty=args.qty, note=args.note)
            except KeyError as exc:
                raise ValueError(_t("Box '{box_id}' gibt es nicht", box_id=args.box_id)) from exc
            ctx.out(_t("Angelegt: #{id} {name}", id=item.id, name=item.name))
            return 0
        if args.inv_cmd == "rm":
            try:
                store.remove_item(args.item_id)
            except KeyError as exc:
                raise ValueError(str(exc)) from exc
            ctx.out(_t("Entfernt: #{item_id}", item_id=args.item_id))
            return 0
        if args.inv_cmd == "mv":
            box_id = None if args.box_id == "-" else args.box_id
            try:
                item = store.move_item(args.item_id, box_id)
            except KeyError as exc:
                raise ValueError(str(exc)) from exc
            ctx.out(_t("Verschoben: #{id} → {value}", id=item.id, value=item.box_id or 'ohne Box'))
            return 0
        if args.inv_cmd == "find":
            hits = store.search(" ".join(args.query))
            if not hits:
                ctx.out(_t("Keine Treffer"))
                return 0
            for hit in hits:
                ctx.out(hit.text())
            return 0
        if args.inv_cmd == "lend":
            due = _parse_due(args.due)
            loan = store.lend(args.item, args.person, due=due)
            ctx.out(_t("Verliehen: #{id} {item} an {person}", id=loan.id, item=loan.item, person=loan.person))
            return 0
        if args.inv_cmd == "return":
            try:
                loan = store.give_back(args.loan_id)
            except KeyError as exc:
                raise ValueError(str(exc)) from exc
            ctx.out(_t("Zurückgegeben: #{id} {item}", id=loan.id, item=loan.item))
            return 0
        if args.inv_cmd == "loans":
            today = datetime.now().date()
            rows = store.loans(open_only=not args.all)
            if not rows:
                ctx.out(_t("Keine offenen Verleihposten") if not args.all else _t("Keine Verleihposten"))
                return 0
            for loan in rows:
                ctx.out(_loan_line(loan, today))
            return 0
        if args.inv_cmd == "label":
            return _run_label(args, ctx, store)
        raise ValueError(_t("Unbekannter Unterbefehl '{inv_cmd}'", inv_cmd=args.inv_cmd))


def _run_box(args: argparse.Namespace, ctx: CliContext, store: InventoryStore) -> int:
    if args.box_cmd == "add":
        box = store.add_box(args.id, args.ort, note=args.note)
        ctx.out(_t("Angelegt: {id} ({location})", id=box.id, location=box.location))
        return 0
    if args.box_cmd == "list":
        boxes = store.boxes()
        if not boxes:
            ctx.out(_t("Keine Boxen angelegt"))
            return 0
        for box in boxes:
            ctx.out(_box_line(box))
        return 0
    if args.box_cmd == "show":
        try:
            box = store.box(args.id)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc
        ctx.out(_box_line(box))
        for item in store.items(box.id):
            ctx.out(_item_line(item))
        return 0
    if args.box_cmd == "rm":
        try:
            store.remove_box(args.id)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc
        ctx.out(_t("Gelöscht: {id}", id=args.id))
        return 0
    raise ValueError(_t("Unbekannter Unterbefehl '{box_cmd}'", box_cmd=args.box_cmd))


def _run_label(args: argparse.Namespace, ctx: CliContext, store: InventoryStore) -> int:
    cfg = ctx.load_config()
    profile = ctx.load_profile()
    tape = current_tape(cfg)

    if args.label_cmd == "box":
        try:
            box = store.box(args.id)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc
        counters = numbering.counter_store(cfg)
        result, meta, counter_keys = render_box_label(box, profile, counters=counters, tape=tape,
                                                       source="cli")
        printed = ctx.emit_label(result, meta)
        if printed:
            for key in counter_keys:
                counters.commit(key)
        return 0

    if args.label_cmd == "content":
        try:
            box = store.box(args.id)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc
        lines = contents_lines(box, store.items(box.id))
        result, meta = render_lines_label(lines, profile, tape=tape, title=_t("Inhalt {id}", id=box.id),
                                          source="cli")
        ctx.emit_label(result, meta)
        return 0

    if args.label_cmd == "loan":
        try:
            loan = store.loan(args.loan_id)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc
        lines = loan_lines(loan)
        result, meta = render_lines_label(lines, profile, tape=tape, title=_t("Verleih {item}", item=loan.item),
                                          source="cli")
        ctx.emit_label(result, meta)
        return 0

    raise ValueError(_t("Unbekannter Unterbefehl '{label_cmd}'", label_cmd=args.label_cmd))
