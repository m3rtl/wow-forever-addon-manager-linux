"""Kommandozeilen-Oberflaeche des Addon-Managers (nutzt nur wfa_core)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import wfa_core as core
from wfa_core import ApiError, InstallPlan, Manager
from wfa_i18n import N_, _

USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
COLORS = {"red": "31", "green": "32", "yellow": "33", "cyan": "36", "grey": "90", "bold": "1"}
STATUS_COLOR = {core.UPDATE: "green", core.CURRENT: "cyan", core.NEWER: "yellow", core.UNKNOWN: "yellow",
                core.NOKEY: "yellow", core.UNASSIGNED: "grey", core.ERROR: "red", core.NO_FOREVER: "yellow",
                core.HELD: "grey", core.SKIPPED: "grey"}
CHANNEL_LABEL = {"release": N_("Nur Release"), "beta": N_("Beta"), "alpha": N_("Alpha")}
FOREVER_COLOR = {"ok": "green", "veraltet": "yellow", "nein": "red"}


class Quit(Exception):
    pass


def paint(text, color=None):
    if not USE_COLOR or not color:
        return text
    return f"\033[{COLORS[color]}m{text}\033[0m"


def ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        raise Quit()


def yn(prompt):
    return ask(prompt + " " + _("[j/N]") + " ").lower() in ("j", "ja", "y", "yes")


def parse_selection(text, maxn):
    out = []
    for tok in re.split(r"[\s,]+", text.strip()):
        if not tok:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", tok)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a < 1 or b > maxn or a > b:
            return None
        out += [n for n in range(a, b + 1) if n not in out]
    return out


# ---------------------------------------------------------------- Einrichtung

def print_candidates(cands):
    for i, c in enumerate(cands, 1):
        print(f"  {i}) {c}")


def setup_flow(mgr):
    """Erststart: AddOns-Ordner finden/wählen. -> True wenn eingerichtet."""
    print(paint(_("Kein AddOns-Ordner von WoW: Forever eingerichtet."), "yellow"))
    cands = mgr.find_installs()
    if cands:
        print(_("Gefundene Installationen:"))
        print_candidates(cands)
    else:
        print(_("Keine Installation automatisch gefunden."))
    while True:
        sel = ask(_("Nummer wählen, m = Pfad manuell eingeben, Enter = abbrechen: "))
        if not sel:
            return False
        if sel.lower() == "m":
            path = ask(_("Pfad (…/_forever_ oder …/Interface/AddOns): "))
            if not path:
                continue
        else:
            s = parse_selection(sel, len(cands))
            if not s or len(s) != 1:
                print(_("Ungültige Eingabe."))
                continue
            path = str(cands[s[0] - 1])
        ok, hint = mgr.validate_addons_dir(path)
        if hint:
            print(paint(hint, "yellow" if ok else "red"))
        if not ok:
            continue
        if hint.startswith("Warnung") and not yn(_("Trotzdem verwenden?")):
            continue
        try:
            mgr.set_addons_dir(path)
        except (ValueError, OSError) as e:
            print(paint(_("Fehler: {error}").format(error=e), "red"))
            continue
        print(_("AddOns-Ordner gespeichert: {path}").format(path=mgr.addons_dir))
        return True


# ---------------------------------------------------------------- Anzeige

def header(mgr):
    print(paint(_("== WoW: Forever Addon-Manager {version} ==").format(version=core.__version__), "bold"))
    print(_("AddOns:     {path}").format(path=mgr.addons_dir))
    client = (_("(Client {version})").format(version=mgr.client_version) if mgr.client_version
              else _("(aus den Addons geschätzt)"))
    print(_("Interface:  {interface} {client}").format(interface=mgr.client_interface, client=client))
    print(_("Download-Ordner: {summary}").format(summary=mgr.download_summary()))
    state = mgr.cf_key_state()
    if state == "fehlt":
        print(paint(_("CurseForge: kein API-Key – kostenlos unter {url} erzeugen, dann Taste k.").format(url=core.CF_KEY_URL), "yellow"))
    elif state == "ungültig":
        print(paint(_("CurseForge: Key ungültig oder abgelehnt (Taste k)."), "red"))
    else:
        print(_("CurseForge: Key {state}: {key}").format(state=_(state), key=core.mask(mgr.api_key)))


def table(mgr, pkgs):
    heads = [_("Nr"), _("Addon"), _("Installiert"), _("Verfügbar"), _("Quelle"), _("Forever"), _("Status")]
    data = []
    for i, p in enumerate(pkgs, 1):
        name = p.name if len(p.name) <= 38 else p.name[:37] + "…"
        data.append([(str(i), None), (name, None), (core.display_version(p.local_version) or "?", None),
                     ((core.display_version(p.remote.version) if p.remote else "–")
                      + {"beta": " β", "alpha": " α"}.get(p.channel, ""), None), (p.source, None),
                     (_(p.forever), FOREVER_COLOR.get(p.forever)), (_(p.status), STATUS_COLOR.get(p.status))])
    w = [max(len(h), *(len(row[c][0]) for row in data)) if data else len(h) for c, h in enumerate(heads)]
    print(paint("  ".join(h.ljust(w[c]) for c, h in enumerate(heads)), "bold"))
    for row in data:
        print("  ".join(paint(t.rjust(w[c]) if c == 0 else t.ljust(w[c]), col) for c, (t, col) in enumerate(row)))
    for p in pkgs:
        if p.pin:
            print(paint(f"* {p.name}: {core.pin_text(p.pin)}", "grey"))
    for n in dict.fromkeys(mgr.notes):
        print(paint("! " + n, "yellow"))


def refresh(mgr):
    print(_("Prüfe Versionen ..."))
    pkgs = mgr.scan()
    mgr.check(pkgs)
    return pkgs


# ---------------------------------------------------------------- Installation

def show_plan(plan):
    print(paint(f"--- {plan.name}", "bold"))
    for w in plan.warnings:
        print(paint("  " + w, "red" if plan.needs_strong_confirm and "Hauptdatei" in w else "yellow"))
    print("  {} -> {}  ({})".format(plan.old_version or _("(neu)"), plan.new_version or "?", plan.source))
    print(_("  Ordner: {folders}").format(folders=", ".join(plan.install_folders)))


def confirm_apply(mgr, plans):
    """-> Liste der Installationsergebnisse (leer, wenn nichts installiert wurde)."""
    plans = list(plans)
    results = []
    try:
        if not plans:
            return results
        keep = []
        for p in plans:
            show_plan(p)
            if p.needs_strong_confirm:
                if ask(_("  Trotzdem installieren? Zum Bestätigen 'ja' eingeben: ")).lower() != "ja":
                    print(_("  Übersprungen."))
                    mgr.discard(p)
                    continue
            keep.append(p)
        if not keep:
            return results
        try:
            deps = mgr.resolve_deps(keep)
        except ApiError as e:
            print(paint(_("Abhängigkeiten nicht prüfbar: {error}").format(error=e), "yellow"))
            deps = []
        for dn in deps:
            if not dn.cand:
                print(paint(_("  Benötigt: {name} – {note} ({reason})").format(name=dn.name, note=dn.note, reason=dn.reason), "yellow"))
            elif yn(_("  Benötigt: {name} ({reason}) – mitinstallieren?").format(name=dn.name, reason=dn.reason)):
                try:
                    plans.append(mgr.plan_candidate(dn.cand))
                    keep.append(plans[-1])
                    show_plan(plans[-1])
                except ApiError as e:
                    print(paint("  {}: {}".format(dn.name, e), "red"))
        if mgr.wow_running() and not yn(paint(_("WoW scheint zu laufen! Trotzdem fortfahren?"), "yellow")):
            return results
        if not yn(_("{n} Paket(e) installieren?").format(n=len(keep))):
            print(_("Abgebrochen."))
            return results
        for r in mgr.apply(keep):
            results.append(r)
            print(paint(f"{r.name}: {r.message}", "green" if r.ok else "red")
                  + (_("  (Sicherung: {name})").format(name=r.backup_set) if r.backup_set else ""))
    finally:
        for p in plans:
            mgr.discard(p)
    return results


def browser_flow(mgr, url, hint_key=None, label=None, queue=False):
    """-> (Status, Ergebnisse); Status: "done" | "skip" | "abort" | "none".
    queue=True: Strg+C fragt "s = überspringen, q = abbrechen"."""
    watch = mgr.download_watch()
    print(_("Öffne {url}").format(url=url))
    print(paint((f"{label}: " if label else "") + _("Lade die Datei für WoW: Forever herunter."), "bold"))
    print(_("Falls nicht vorgefiltert: Filter 'Game Version/Flavor' → 'Forever' wählen."))
    if watch["ask"]:
        print(_("Browser fragt nach Speicherort – bitte in einen dieser Ordner speichern."))
    since = time.time()
    mgr.open_browser(url)
    print(_("Überwachte Ordner: {folders}").format(folders=", ".join(core.tilde(f) for f in watch["folders"]) or _("(keiner gefunden)")))
    print(_("Warte auf neue .zip (Strg+C bricht ab, max. 10 Minuten) ..."))
    cancel = threading.Event()
    try:
        z = mgr.wait_for_download(since, 600, cancel, watch["folders"])
    except KeyboardInterrupt:
        cancel.set()
        print()
        if queue and ask(_("s = überspringen, q = alle abbrechen [s/q]: ")).lower() != "q":
            return "skip", []
        print(_("Abgebrochen."))
        return "abort", []
    if not z:
        print(_("Keine neue Zip gefunden."))
        return "none", []
    print(_("Gefunden: {name}").format(name=z.name))
    try:
        plan = mgr.plan_zip(z, hint_key)
    except ApiError as e:
        print(paint("{}: {}".format(z.name, e), "red"))
        return "done", []
    return "done", confirm_apply(mgr, [plan])


def browser_queue(mgr, items):
    """items: [(Name, Paket)]. Nacheinander abarbeiten, am Ende Gesamtübersicht."""
    installed, skipped, errors = [], [], []
    for i, (name, p) in enumerate(items):
        status, results = browser_flow(mgr, mgr.browser_url(p), p.key, _("Browser-Download {i} von {n}: {name}").format(i=i + 1, n=len(items), name=name), True)
        for r in results:
            (installed if r.ok else errors).append(r.name if r.ok else f"{r.name}: {r.message}")
        if status in ("skip", "none") or (status == "done" and not results):
            skipped.append(name)
        if status == "abort":
            skipped += [n for n, _p in items[i:]]
            break
    print(paint("\n" + _("Gesamtergebnis"), "bold"))
    for title, lst in ((_("Installiert"), installed), (_("Übersprungen"), skipped), (_("Fehler"), errors)):
        if lst:
            print(f"  {title} ({len(lst)}): " + "; ".join(lst))


def menu_updates(mgr, pkgs):
    arg = ask(_("Nummern (z. B. 1 3 5-7), 'a' = alle Updates, Enter = zurück: "))
    if not arg:
        return
    if arg.lower() == "a":
        sel = [i for i, p in enumerate(pkgs, 1) if p.status == core.UPDATE]
    else:
        sel = parse_selection(arg, len(pkgs))
        if sel is None:
            print(_("Ungültige Eingabe."))
            return
    sel = [i for i in sel if pkgs[i - 1].remote]
    if not sel:
        print(_("Nichts auszuwählen."))
        return
    plans, queue = [], []
    try:
        for i in sel:
            p = pkgs[i - 1]
            try:
                plans.append(mgr.plan_update(p))
            except ApiError as e:
                print(paint("{}: {}".format(p.name, e), "red"))
                if e.kind == "download":
                    queue.append((p.name, p))
    except BaseException:
        for pl in plans:
            mgr.discard(pl)
        raise
    confirm_apply(mgr, plans)
    if queue and yn(_("{n} Datei(en) nacheinander im Browser laden?").format(n=len(queue))):
        browser_queue(mgr, queue)


def menu_version(mgr, pkgs):
    s = parse_selection(ask(_("Addon-Nummer (Enter = zurück): ")), len(pkgs))
    if not s:
        return False
    p = pkgs[s[0] - 1]
    if p.meta.get("unassigned"):
        print(_("Erst zuordnen (Taste z)."))
        return False
    print(_("{name}: Kanal {channel}").format(name=p.name, channel=_(CHANNEL_LABEL.get(p.channel, N_("Standard"))))
          + (f"; {core.pin_text(p.pin)}" if p.pin else ""))
    print(_("[1] Bestimmte Version installieren  [2] Kanal setzen")
          + ("  " + _("[3] Festhalten/Auslassen aufheben") if p.pin else ""))
    c = ask(_("Auswahl (Enter = zurück): "))
    if c == "1":
        install_version(mgr, p)
    elif c == "2":
        print(_("[0] Standard (wie Einstellung)  [1] Nur Release  [2] Beta  [3] Alpha"))
        ch = {"0": None, "1": "release", "2": "beta", "3": "alpha"}
        k = ask(_("Kanal (Enter = zurück): "))
        if k in ch:
            mgr.set_channel(p.key, ch[k])
    elif c == "3" and p.pin:
        mgr.clear_pin(p.key)
    else:
        return False
    return True


def install_version(mgr, p):
    page, remotes = 0, []
    while True:
        res, more = mgr.versions(p, page)
        remotes += res
        if not remotes:
            print(_("Keine Versionen gefunden."))
            return
        ident = mgr.installed_ident(p)
        for i, r in enumerate(remotes, 1):
            mark = paint(" " + _("[installiert]"), "cyan") if ident is not None and r.ident == ident else ""
            print(f"  {i:2}) {r.display or r.version}  {r.file_date[:10]}  {core.TYPE_NAMES.get(r.rtype, 'Release')}{mark}")
        arg = ask(_("Nummer, 'm' = mehr laden (Enter = zurück): ") if more else _("Nummer (Enter = zurück): ")).lower()
        if arg == "m" and more:
            page += 1
            continue
        s = parse_selection(arg, len(remotes))
        if not s:
            return
        break
    r, newest = remotes[s[0] - 1], mgr.newest_allowed(p, remotes)
    mode = None
    if r.ident != newest.ident:
        k = ask(_("Danach: [1] nur neuere Versionen auslassen  [2] auf dieser Version festhalten (Enter = 1): "))
        mode = "hold" if k == "2" else "skip"
    confirm_apply(mgr, [mgr.plan_version(p, r, mode, newest)])


def pick(cands, what=None):
    what = what or _("Nummer (Enter = zurück): ")
    if not cands:
        print(_("Keine Treffer."))
        return None
    for i, c in enumerate(cands, 1):
        fv = {True: _("ja"), False: _("nein"), None: "?"}[c.has_forever]
        mark = paint(" " + _("[installiert]"), "cyan") if c.installed else ""
        extra = f" – {c.author}" if c.author else ""
        dl = " – " + _("{n} Downloads").format(n=f"{c.downloads:,}") if c.downloads else ""
        print(f"  {i:2}) {c.name}{extra}{dl} – " + _("Forever-Datei: {state}").format(state=fv) + mark)
    s = parse_selection(ask(what), len(cands))
    return cands[s[0] - 1] if s else None


def install_candidate(mgr, cand):
    try:
        plan = mgr.plan_candidate(cand)
    except ApiError as e:
        print(paint(f"{e}", "red"))
        if e.kind in ("nofile", "download") and yn(_("Im Browser herunterladen?")):
            browser_flow(mgr, mgr.browser_url(cand))
        return
    confirm_apply(mgr, [plan])


def forbidden_alternatives(mgr, q):
    print(paint(_("Suche ist für diesen API-Key nicht freigeschaltet."), "yellow"))
    print(_("Alternativen: [1] Beliebte Forever-Addons  [2] CurseForge-Projekt-ID eingeben  [3] Im Browser suchen"))
    c = ask(_("Auswahl (Enter = zurück): "))
    if c == "1":
        cand = pick(mgr.featured())
        if cand:
            install_candidate(mgr, cand)
    elif c == "2":
        i = ask(_("Projekt-ID: "))
        if i.isdigit():
            cand = pick(mgr.resolve_input(i))
            if cand:
                install_candidate(mgr, cand)
        elif i:
            print(_("Ungültige ID."))
    elif c == "3":
        url = mgr.browser_url(None, q)
        print(_("Öffne {url}").format(url=url))
        mgr.open_browser(url)


def menu_new(mgr, pkgs):
    q = ask(_("Suchbegriff, CF-Projekt-ID, gh:owner/repo, URL, Zip-Pfad, 'p' = beliebte Addons (Enter = zurück): "))
    if not q:
        return
    try:
        if q.lower() == "p":
            cand = pick(mgr.featured())
            if cand:
                install_candidate(mgr, cand)
            return
        r = mgr.resolve_input(q)
    except ApiError as e:
        if e.kind == "forbidden":
            forbidden_alternatives(mgr, q)
        else:
            print(paint(_("Fehler: {error}").format(error=e), "red"))
        return
    if isinstance(r, InstallPlan):
        confirm_apply(mgr, [r])
        return
    cand = pick(r)
    if cand:
        install_candidate(mgr, cand)


def menu_assign(mgr, pkgs):
    un = [p for p in pkgs if p.meta.get("unassigned")]
    if not un:
        print(_("Keine nicht zugeordneten Ordner."))
        return
    for i, p in enumerate(un, 1):
        print(f"  {i}) {p.name}")
    sel = ask(_("Ordner (z. B. 1 3; Enter = zurück): "))
    s = parse_selection(sel, len(un)) if sel else None
    if sel and s is None:
        print(_("Ungültige Eingabe."))
    if not s:
        return
    folders = [un[i - 1].name for i in s]
    title = un[s[0] - 1].note or folders[0]
    try:
        sugs = mgr.suggest_assignments(un[s[0] - 1])
    except ApiError as e:
        print(paint(_("Vorschläge nicht ermittelbar: {error}").format(error=e), "yellow"))
        sugs = []
    for i, sg in enumerate(sugs, 1):
        print(f"  v{i}) {sg.cand.name}  ({sg.cand.source} {sg.cand.ident})  – {sg.reason}")
    q = ask((_("Vorschlag (v1 …), CF-Projekt-ID, gh:owner/repo oder CF-Suchbegriff [{title}]: ") if sugs
             else _("CF-Projekt-ID, gh:owner/repo oder CF-Suchbegriff [{title}]: ")).format(title=title)) or title
    pre = re.fullmatch(r"v(\d+)", q.lower())
    if pre and 1 <= int(pre.group(1)) <= len(sugs):
        c = sugs[int(pre.group(1)) - 1].cand
        q = f"gh:{c.ident}" if c.source == "GH" else str(c.ident)
    repo = None
    if q.lower().startswith("gh:") or "github.com/" in q.lower():
        try:
            repo = mgr.assign_target(q).ident
        except ApiError as e:
            print(paint(_("Fehler: {error}").format(error=e), "red"))
            return
    try:
        if repo:
            mgr.assign_folders(folders, title, gh=repo)
        elif q.isdigit():
            mgr.assign_folders(folders, title, cf_id=int(q))
        else:
            try:
                cand = pick(mgr.search(q))
            except ApiError as e:
                if e.kind == "forbidden":
                    print(paint(_("Suche ist für diesen API-Key nicht freigeschaltet. "
                                  "Gib die CF-Projekt-ID oder gh:owner/repo direkt ein."), "yellow"))
                else:
                    print(paint(_("Fehler: {error}").format(error=e), "red"))
                return
            if not cand:
                return
            mgr.assign_folders(folders, cand.name, cf_id=int(cand.ident))
    except (ValueError, OSError) as e:
        print(paint(_("Fehler: {error}").format(error=e), "red"))
        return
    print(_("Zugeordnet: {folders}").format(folders=", ".join(folders)))


def export_cmd(mgr, target):
    mgr.log = lambda s: print(s, file=sys.stderr)
    pkgs = mgr.scan()
    mgr.check(pkgs)
    data = mgr.export_data(pkgs)
    out = core.export_text(data) if target.lower().endswith(".txt") else json.dumps(data, indent=2, ensure_ascii=False)
    if target == "-":
        print(out)
    else:
        try:
            Path(target).expanduser().write_text(out + "\n", "utf-8")
        except OSError as e:
            print(paint(_("Export nicht gespeichert: {error}").format(error=e), "red"), file=sys.stderr)
            return 1
        print(_("{n} Addons exportiert nach {target}").format(n=len(data["packages"]), target=target))
    if not mgr.api_key:
        print(_("Hinweis: Ohne CurseForge-Key werden CF-Addons evtl. nicht erkannt und fehlen dann in der Liste."), file=sys.stderr)
    if not data["packages"]:
        print(_("Hinweis: Keine übertragbaren Addons (CurseForge-/GitHub-Zuordnung fehlt)."), file=sys.stderr)
    if data["untransferable"]:
        print(_("Nicht übertragbar: {names}").format(names=", ".join(data["untransferable"])), file=sys.stderr)
    return 0


def import_cmd(mgr, source):
    p = Path(source).expanduser()
    try:
        try:
            is_file = p.is_file()
        except OSError:   # z. B. zu langer Name: ist dann Text
            is_file = False
        entries = core.parse_import(p.read_text("utf-8-sig") if is_file else source)
    except (OSError, UnicodeDecodeError) as e:
        print(paint(_("Datei nicht lesbar: {error}").format(error=e), "red"))
        return 1
    except ApiError as e:
        print(paint(str(e), "red"))
        return 1
    mgr.scan()
    items = mgr.import_preview(entries)
    for it in items:
        print(f"  {it['name']}" + (f"  ({it['source']})" if it["name"] != it["source"] else "") + (f" [{it['channel']}]" if it.get("channel") else "")
              + (paint("  – " + _("schon installiert"), "cyan") if it["installed"] else ""))
    todo = [it for it in items if not it["installed"]]
    if not todo or not yn(_("{n} Addon(s) installieren?").format(n=len(todo))):
        return 0
    plans = []
    try:
        for it in todo:
            try:
                plans.append(mgr.plan_candidate(mgr.import_candidate(it), it.get("channel")))
            except ApiError as e:
                print(paint("{}: {}".format(it["name"], e), "red"))
        results = confirm_apply(mgr, plans)
    finally:
        for pl in plans:
            mgr.discard(pl)
    wanted = {pl.key for pl in plans}   # mitinstallierte Abhängigkeiten nicht mitzählen
    bad = len(todo) - sum(1 for r in results if r.ok and r.key in wanted)
    if bad and (results or not plans):
        print(paint(_("{bad} von {n} Addon(s) nicht installiert.").format(bad=bad, n=len(todo)), "yellow"))
    return 1 if todo and not any(r.ok for r in results) and (results or not plans) else 0


def menu_browser(mgr, pkgs):
    s = ask(_("Nummer des Pakets (Enter = zurück): "))
    sel = parse_selection(s, len(pkgs)) if s else None
    if s and sel is None:
        print(_("Ungültige Eingabe."))
    if not sel:
        return
    p = pkgs[sel[0] - 1]
    if p.meta.get("unassigned"):
        print(_("Erst zuordnen (Taste z)."))
        return
    browser_flow(mgr, mgr.browser_url(p), p.key)


def menu_key(mgr):
    print(_("Key-Status: {state}").format(state=_(mgr.cf_key_state())))
    v = ask(_("Neuer Key, '-' zum Löschen, Enter = unverändert: "))
    if v == "-":
        mgr.set_cf_key(None)
    elif v:
        mgr.set_cf_key(v)
    else:
        return False
    return True


def menu_restore(mgr):
    sets = [(b.created, b) for b in mgr.list_backups()] + [(v.created, v) for v in mgr.list_sv_backups()]
    sets = [x[1] for x in sorted(sets, key=lambda x: x[0], reverse=True)]
    if not sets:
        print(_("Keine Sicherungen vorhanden."))
        return False
    for i, b in enumerate(sets, 1):
        if isinstance(b, core.SvSet):
            print(_("  {i}) {name}: Einstellungen (SavedVariables), {n} Addons").format(i=i, name=b.name, n=len(b.addons)))
        else:
            print(f"  {i}) {b.name}: {', '.join(b.folders)}")
    s = ask(_("Sicherung wählen (Enter = zurück): "))
    sel = parse_selection(s, len(sets)) if s else None
    if s and sel is None:
        print(_("Ungültige Eingabe."))
    if not sel:
        return False
    b = sets[sel[0] - 1]
    if isinstance(b, core.SvSet):
        return restore_sv_cli(mgr, b)
    if not b.folders or not yn(_("{n} Ordner wiederherstellen (aktuelle Versionen werden vorher gesichert)?").format(n=len(b.folders))):
        return False
    if mgr.wow_running() and not yn(paint(_("WoW scheint zu laufen! Trotzdem fortfahren?"), "yellow")):
        return False
    r = mgr.restore(b)
    print(paint(r.message, "green" if r.ok else "red"))
    return r.ok


def restore_sv_cli(mgr, b):
    running = mgr.wow_running()
    if running:
        print(paint(_("WoW läuft – Einstellungen lassen sich nur bei beendetem WoW wiederherstellen."), "red"))
        return False
    if running is None and not yn(paint(_("Ob WoW läuft, ist im Flatpak nicht erkennbar. Ist WoW beendet?"), "yellow")):
        return False
    print(_("Addons: {names}").format(names=", ".join(b.addons)))
    s = ask(_("Nur bestimmte Addons (Namen, durch Leerzeichen getrennt)? Enter = alle: "))
    only = s.split() if s else None
    if not yn(_("Einstellungen wiederherstellen (aktueller Stand wird vorher gesichert)?")):
        return False
    r = mgr.restore_sv(b, only)
    print(paint(r.message, "green" if r.ok else "red"))
    return r.ok


def menu_history(mgr):
    entries = mgr.read_history(30)
    if not entries:
        print(_("Noch keine Änderungen protokolliert."))
    for e in entries:
        old, new = e.get("old"), e.get("new")
        ver = f"  {old or '–'} → {new or '–'}" if (old or new) else ""
        print(f"  {str(e.get('ts') or '?').replace('T', ' ')}  {_(str(e.get('kind') or '')) if e.get('kind') else '':<17} {str(e.get('name') or '')}{ver}"
              + (_("  [Sicherung {name}]").format(name=e["backup"]) if e.get("backup") else "")
              + (_("  [Einstellungen {name}]").format(name=e["sv"]) if e.get("sv") else ""))
    return False


def menu_uninstall(mgr, pkgs):
    s = ask(_("Nummern der zu deinstallierenden Pakete (z. B. 1 3 5-7, Enter = zurück): "))
    sel = parse_selection(s, len(pkgs)) if s else None
    if s and sel is None:
        print(_("Ungültige Eingabe."))
    if not sel:
        return False
    plans = [mgr.plan_uninstall(pkgs[i - 1]) for i in sel]
    for p in plans:
        print(paint(f"--- {p.name}", "bold"))
        print(_("  Ordner: {folders}").format(folders=", ".join(p.folders) or _("(keine)")))
        for w in p.warnings:
            print(paint("  ! " + w, "yellow"))
    print(_("Die Ordner werden in ein Backup verschoben (Menü w: Wiederherstellen). Einstellungen (SavedVariables/WTF) bleiben erhalten."))
    plans = [p for p in plans if p.folders]
    if not plans:
        return False
    if mgr.wow_running() and not yn(paint(_("WoW scheint zu laufen! Trotzdem fortfahren?"), "yellow")):
        return False
    if not yn(_("{n} Paket(e) deinstallieren?").format(n=len(plans))):
        print(_("Abgebrochen."))
        return False
    for r in mgr.uninstall(plans):
        print(paint(f"{r.name}: {r.message}", "green" if r.ok else "red")
              + (_("  (Sicherung: {name})").format(name=r.backup_set) if r.backup_set else ""))
    return True


# ---------------------------------------------------------------- Gesamtstaende und Aufraeumen

KIND_LABEL = {"orphan_sv": N_("Einstellungen ohne Addon"), "nested": N_("Verschachtelter Ordner"),
              "no_toc": N_("Ordner ohne TOC")}


def write_allowed(mgr):
    """Nur bei beendetem WoW schreiben; ist das nicht feststellbar (Flatpak), wird verweigert."""
    running = mgr.wow_running()
    if running:
        print(paint(_("WoW läuft. Bitte zuerst beenden."), "red"), file=sys.stderr)
    elif running is None:
        print(paint(_("Ob WoW läuft, ist hier nicht feststellbar. Zur Sicherheit wird nichts geändert."), "red"),
              file=sys.stderr)
    return running is False


def _iso(s):
    return str(s).replace("T", " ")


def snapshot_cmd(mgr, label):
    import wfa_snapshot
    try:
        snap = wfa_snapshot.create(mgr.addons_dir, mgr.wtf_dir(), mgr.paths.data_dir / "snapshots", label,
                                   mgr.client_version or "")
    except OSError as e:
        print(paint(str(e), "red"), file=sys.stderr)
        return 1
    print(_("Gesamtstand {id} angelegt ({size}).").format(id=snap.id, size=core.fmt_size(snap.size)))
    return 0


def snapshots_cmd(mgr):
    import wfa_snapshot
    snaps = wfa_snapshot.list_snapshots(mgr.paths.data_dir / "snapshots")
    if not snaps:
        print(_("Keine Gesamtstände vorhanden."))
    for s in snaps:
        print(_("{id}  {created}  {n:>3} Addons  {size:>9}  {label}").format(id=s.id, created=_iso(s.created), n=len(s.addons),
                                                                  size=core.fmt_size(s.size), label=_(s.label) if s.label else ""))
    return 0


def restore_snapshot_cmd(mgr, sid):
    import wfa_snapshot
    root = mgr.paths.data_dir / "snapshots"
    snap = next((s for s in wfa_snapshot.list_snapshots(root) if s.id == sid), None)
    if snap is None:
        print(paint(_("Gesamtstand {id} nicht gefunden (siehe --snapshots).").format(id=sid), "red"), file=sys.stderr)
        return 1
    if not write_allowed(mgr):
        return 1
    try:
        safety = wfa_snapshot.restore(snap, mgr.addons_dir, mgr.wtf_dir(), root)
    except (OSError, ValueError) as e:
        print(paint(str(e), "red"), file=sys.stderr)
        return 1
    print(_("Gesamtstand {id} wiederhergestellt. Vorheriger Stand gesichert als {safe}.").format(id=sid, safe=safety.id))
    return 0


def cleanup_cmd(mgr, apply):
    import wfa_cleanup
    findings = wfa_cleanup.scan(mgr.addons_dir, mgr.wtf_dir())
    if not findings:
        print(_("Nichts zum Aufräumen gefunden."))
        return 0
    for f in findings:
        print("{:<26} {:>9}  {}".format(_(KIND_LABEL.get(f.kind, f.kind)), core.fmt_size(f.size), f.path))
    if not apply:
        print(_("Nur aufgelistet. Mit --cleanup --apply in den Papierkorb verschieben."))
        return 0
    if not write_allowed(mgr):
        return 1
    code = 0
    try:
        results = wfa_cleanup.apply(findings, mgr.addons_dir, mgr.paths.data_dir / "trash")
    except (OSError, ValueError) as e:
        print(paint(str(e), "red"), file=sys.stderr)
        return 1
    for _f, ok, msg in results:
        print(paint(msg, "green" if ok else "red"))
        code = code or (0 if ok else 1)
    return code


def update_cmd(mgr, args):
    """--update / --run: ohne Rueckfragen aktualisieren; bei --run danach CMD starten (auch nach Fehlern)."""
    import wfa_unattended
    code = 1
    try:
        res = wfa_unattended.run_update(mgr, log=print, quiet=args.quiet)
        code = res.exit_code
    except KeyboardInterrupt:
        print(file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(paint(_("Update fehlgeschlagen: {error}").format(error=e), "red"), file=sys.stderr)
    if args.run:
        cmd = list(args.run)
        sys.stdout.flush()
        sys.stderr.flush()
        try:
            os.execvp(cmd[0], cmd)
        except OSError as e:
            print(paint(_("Programm konnte nicht gestartet werden: {error}").format(error=e), "red"), file=sys.stderr)
            return 127
    return code


def run(mgr):
    pkgs = refresh(mgr)
    while True:
        print()
        header(mgr)
        table(mgr, pkgs)
        print("\n" + _("[u] Updates  [n] Neu installieren  [z] Zuordnen  [b] Browser-Download  [k] CF-Key  "
                      "[e] Beta: {beta}  [v] Version/Kanal  [r] Neu prüfen  [d] Deinstallieren  [w] Wiederherstellen  "
                      "[h] Verlauf  [q] Ende").format(beta=_("an") if mgr.cfg["include_beta"] else _("aus")))
        c = ask("> ").lower()
        if c == "q":
            return
        try:
            again = c == "r"
            if c == "u":
                menu_updates(mgr, pkgs)
                again = True
            elif c == "n":
                menu_new(mgr, pkgs)
                again = True
            elif c == "z":
                menu_assign(mgr, pkgs)
                again = True
            elif c == "b":
                menu_browser(mgr, pkgs)
                again = True
            elif c == "v":
                again = menu_version(mgr, pkgs)
            elif c == "k":
                again = menu_key(mgr)
            elif c == "e":
                mgr.set_include_beta(not mgr.cfg["include_beta"])
                again = True
            elif c == "d":
                again = menu_uninstall(mgr, pkgs)
            elif c == "w":
                again = menu_restore(mgr)
            elif c == "h":
                menu_history(mgr)
            elif c:
                print(_("Unbekannte Eingabe."))
            if again:
                pkgs = refresh(mgr)
        except ApiError as e:
            print(paint(_("Fehler: {error}").format(error=e), "red"))
        except OSError as e:
            print(paint(_("Dateifehler: {error}").format(error=e), "red"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wow-forever-addon-manager",
                                 description=_("Addon-Manager für WoW: Forever (CurseForge/GitHub, mit Sicherungen)."))
    ap.add_argument("--cli", action="store_true", help=_("Kommandozeile erzwingen (statt GUI)"))
    ap.add_argument("--check", action="store_true", help=_("nur Tabelle ausgeben, nicht interaktiv"))
    ap.add_argument("--addons-dir", metavar=_("PFAD"), help=_("AddOns-Ordner (nur für diesen Lauf, wird nicht gespeichert)"))
    ap.add_argument("--export", metavar=_("PFAD"), help=_("Addon-Liste als JSON (oder Kurztext bei .txt) schreiben, „-“ = stdout"))
    ap.add_argument("--import", dest="import_list", metavar=_("PFAD|TEXT"),
                    help=_("Addon-Liste aus Datei oder Kurztext (WFA1 cf:… gh:…) installieren"))
    ap.add_argument("--snapshot", nargs="?", const="", metavar=_("BEZEICHNUNG"),
                    help=_("Gesamtstand (AddOns und WTF) sichern, Bezeichnung optional"))
    ap.add_argument("--snapshots", action="store_true", help=_("Gesamtstände auflisten"))
    ap.add_argument("--restore-snapshot", metavar="ID", help=_("Gesamtstand wiederherstellen (ID aus --snapshots)"))
    ap.add_argument("--cleanup", action="store_true", help=_("Funde zum Aufräumen auflisten"))
    ap.add_argument("--apply", action="store_true", help=_("mit --cleanup: Funde in den Papierkorb verschieben"))
    ap.add_argument("--update", action="store_true",
                    help=_("veraltete Addons ohne Rückfragen aktualisieren (nicht bei laufendem WoW); Exit-Code 0 ok, 1 Fehler, 2 übersprungen"))
    ap.add_argument("--quiet", action="store_true", help=_("mit --update: nur Zusammenfassung und Fehler ausgeben"))
    ap.add_argument("--run", nargs=argparse.REMAINDER, metavar="CMD",
                    help=_("nach dem Update CMD starten (impliziert --update), z. B. Steam-Startoption: wfa --update --run %%command%%"))
    ap.add_argument("--version", action="version", version=f"%(prog)s {core.__version__}")
    args = ap.parse_args(argv)
    if args.apply and not args.cleanup:
        ap.error(_("--apply gehört zu --cleanup"))
    if args.run is not None and args.run[:1] == ["--"]:
        args.run = args.run[1:]
    if args.run is not None and not args.run:
        ap.error(_("--run braucht einen Befehl"))
    if args.quiet and not (args.update or args.run):
        ap.error(_("--quiet gehört zu --update"))
    try:
        quiet = args.quiet and bool(args.update or args.run)
        mgr = Manager(addons_dir=args.addons_dir, log=(lambda _s: None) if quiet else print)
        if args.update or args.run:
            return update_cmd(mgr, args)
        if mgr.needs_setup():
            if args.addons_dir:
                print(_("AddOns-Ordner nicht gefunden: {path}").format(path=args.addons_dir), file=sys.stderr)
                return 1
            if args.check or not sys.stdin.isatty():
                print(_("Kein AddOns-Ordner eingerichtet. Gefundene Kandidaten:"))
                cands = mgr.find_installs()
                print_candidates(cands) if cands else print(_("  (keine)"))
                print(_("Starte ohne --check zur Auswahl oder nutze --addons-dir PFAD."))
                return 1
            if not setup_flow(mgr):
                return 1
        if args.snapshot is not None:
            return snapshot_cmd(mgr, args.snapshot)
        if args.snapshots:
            return snapshots_cmd(mgr)
        if args.restore_snapshot:
            return restore_snapshot_cmd(mgr, args.restore_snapshot)
        if args.cleanup:
            return cleanup_cmd(mgr, args.apply)
        if args.export:
            return export_cmd(mgr, args.export)
        if args.import_list:
            return import_cmd(mgr, args.import_list)
        if args.check:
            pkgs = refresh(mgr)
            header(mgr)
            table(mgr, pkgs)
            return 0
        run(mgr)
    except (Quit, KeyboardInterrupt, EOFError):
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
