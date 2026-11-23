"""Kommandozeilen-Oberflaeche des Addon-Managers (nutzt nur wfa_core)."""
from __future__ import annotations

import argparse
import os
import re
import sys
import threading
import time

import wfa_core as core
from wfa_core import ApiError, InstallPlan, Manager

USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
COLORS = {"red": "31", "green": "32", "yellow": "33", "cyan": "36", "grey": "90", "bold": "1"}
STATUS_COLOR = {core.UPDATE: "green", core.CURRENT: "cyan", core.NEWER: "yellow", core.UNKNOWN: "yellow",
                core.NOKEY: "yellow", core.UNASSIGNED: "grey", core.ERROR: "red", core.NO_FOREVER: "yellow"}
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
    return ask(prompt + " [j/N] ").lower() in ("j", "ja", "y", "yes")


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
    print(paint("Kein AddOns-Ordner von WoW: Forever eingerichtet.", "yellow"))
    cands = mgr.find_installs()
    if cands:
        print("Gefundene Installationen:")
        print_candidates(cands)
    else:
        print("Keine Installation automatisch gefunden.")
    while True:
        sel = ask("Nummer wählen, m = Pfad manuell eingeben, Enter = abbrechen: ")
        if not sel:
            return False
        if sel.lower() == "m":
            path = ask("Pfad (…/_forever_ oder …/Interface/AddOns): ")
            if not path:
                continue
        else:
            s = parse_selection(sel, len(cands))
            if not s or len(s) != 1:
                print("Ungültige Eingabe.")
                continue
            path = str(cands[s[0] - 1])
        ok, hint = mgr.validate_addons_dir(path)
        if hint:
            print(paint(hint, "yellow" if ok else "red"))
        if not ok:
            continue
        if hint.startswith("Warnung") and not yn("Trotzdem verwenden?"):
            continue
        try:
            mgr.set_addons_dir(path)
        except (ValueError, OSError) as e:
            print(paint(f"Fehler: {e}", "red"))
            continue
        print(f"AddOns-Ordner gespeichert: {mgr.addons_dir}")
        return True


# ---------------------------------------------------------------- Anzeige

def header(mgr):
    print(paint(f"== WoW: Forever Addon-Manager {core.__version__} ==", "bold"))
    print(f"AddOns:     {mgr.addons_dir}")
    print(f"Interface:  {mgr.client_interface} (Client)")
    print(f"Download-Ordner: {mgr.download_summary()}")
    state = mgr.cf_key_state()
    if state == "fehlt":
        print(paint(f"CurseForge: kein API-Key – kostenlos unter {core.CF_KEY_URL} erzeugen, dann Taste k.", "yellow"))
    elif state == "ungültig":
        print(paint("CurseForge: Key ungültig oder abgelehnt (Taste k).", "red"))
    else:
        print(f"CurseForge: Key {state}: {core.mask(mgr.api_key)}")


def table(mgr, pkgs):
    heads = ["Nr", "Addon", "Installiert", "Verfügbar", "Quelle", "Forever", "Status"]
    data = []
    for i, p in enumerate(pkgs, 1):
        name = p.name if len(p.name) <= 38 else p.name[:37] + "…"
        data.append([(str(i), None), (name, None), (core.display_version(p.local_version) or "?", None),
                     (core.display_version(p.remote.version) if p.remote else "–", None), (p.source, None),
                     (p.forever, FOREVER_COLOR.get(p.forever)), (p.status, STATUS_COLOR.get(p.status))])
    w = [max(len(h), *(len(row[c][0]) for row in data)) if data else len(h) for c, h in enumerate(heads)]
    print(paint("  ".join(h.ljust(w[c]) for c, h in enumerate(heads)), "bold"))
    for row in data:
        print("  ".join(paint(t.rjust(w[c]) if c == 0 else t.ljust(w[c]), col) for c, (t, col) in enumerate(row)))
    for n in dict.fromkeys(mgr.notes):
        print(paint("! " + n, "yellow"))


def refresh(mgr):
    print("Prüfe Versionen ...")
    pkgs = mgr.scan()
    mgr.check(pkgs)
    return pkgs


# ---------------------------------------------------------------- Installation

def show_plan(plan):
    print(paint(f"--- {plan.name}", "bold"))
    for w in plan.warnings:
        print(paint("  " + w, "red" if plan.needs_strong_confirm and "Hauptdatei" in w else "yellow"))
    print(f"  {plan.old_version or '(neu)'} -> {plan.new_version or '?'}  ({plan.source})")
    print("  Ordner: " + ", ".join(plan.install_folders))


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
                if ask("  Trotzdem installieren? Zum Bestätigen 'ja' eingeben: ").lower() != "ja":
                    print("  Übersprungen.")
                    mgr.discard(p)
                    continue
            keep.append(p)
        if not keep:
            return results
        if mgr.wow_running() and not yn(paint("WoW scheint zu laufen! Trotzdem fortfahren?", "yellow")):
            return results
        if not yn(f"{len(keep)} Paket(e) installieren?"):
            print("Abgebrochen.")
            return results
        for r in mgr.apply(keep):
            results.append(r)
            print(paint(f"{r.name}: {r.message}", "green" if r.ok else "red")
                  + (f"  (Sicherung: {r.backup_set})" if r.backup_set else ""))
    finally:
        for p in plans:
            mgr.discard(p)
    return results


def browser_flow(mgr, url, hint_key=None, label=None, queue=False):
    """-> (Status, Ergebnisse); Status: "done" | "skip" | "abort" | "none".
    queue=True: Strg+C fragt "s = überspringen, q = abbrechen"."""
    watch = mgr.download_watch()
    print(f"Öffne {url}")
    print(paint((f"{label}: " if label else "") + "Lade die Datei für WoW: Forever herunter.", "bold"))
    print("Falls nicht vorgefiltert: Filter 'Game Version/Flavor' → 'Forever' wählen.")
    if watch["ask"]:
        print("Browser fragt nach Speicherort – bitte in einen dieser Ordner speichern.")
    since = time.time()
    mgr.open_browser(url)
    print("Überwachte Ordner: " + (", ".join(core.tilde(f) for f in watch["folders"]) or "(keiner gefunden)"))
    print("Warte auf neue .zip (Strg+C bricht ab, max. 10 Minuten) ...")
    cancel = threading.Event()
    try:
        z = mgr.wait_for_download(since, 600, cancel, watch["folders"])
    except KeyboardInterrupt:
        cancel.set()
        print()
        if queue and ask("s = überspringen, q = alle abbrechen [s/q]: ").lower() != "q":
            return "skip", []
        print("Abgebrochen.")
        return "abort", []
    if not z:
        print("Keine neue Zip gefunden.")
        return "none", []
    print(f"Gefunden: {z.name}")
    try:
        plan = mgr.plan_zip(z, hint_key)
    except ApiError as e:
        print(paint(f"{z.name}: {e}", "red"))
        return "done", []
    return "done", confirm_apply(mgr, [plan])


def browser_queue(mgr, items):
    """items: [(Name, Paket)]. Nacheinander abarbeiten, am Ende Gesamtübersicht."""
    installed, skipped, errors = [], [], []
    for i, (name, p) in enumerate(items):
        status, results = browser_flow(mgr, mgr.browser_url(p), p.key, f"Browser-Download {i + 1} von {len(items)}: {name}", True)
        for r in results:
            (installed if r.ok else errors).append(r.name if r.ok else f"{r.name}: {r.message}")
        if status in ("skip", "none") or (status == "done" and not results):
            skipped.append(name)
        if status == "abort":
            skipped += [n for n, _p in items[i:]]
            break
    print(paint("\nGesamtergebnis", "bold"))
    for title, lst in (("Installiert", installed), ("Übersprungen", skipped), ("Fehler", errors)):
        if lst:
            print(f"  {title} ({len(lst)}): " + "; ".join(lst))


def menu_updates(mgr, pkgs):
    arg = ask("Nummern (z. B. 1 3 5-7), 'a' = alle Updates, Enter = zurück: ")
    if not arg:
        return
    if arg.lower() == "a":
        sel = [i for i, p in enumerate(pkgs, 1) if p.status == core.UPDATE]
    else:
        sel = parse_selection(arg, len(pkgs))
        if sel is None:
            print("Ungültige Eingabe.")
            return
    sel = [i for i in sel if pkgs[i - 1].remote]
    if not sel:
        print("Nichts auszuwählen.")
        return
    plans, queue = [], []
    try:
        for i in sel:
            p = pkgs[i - 1]
            try:
                plans.append(mgr.plan_update(p))
            except ApiError as e:
                print(paint(f"{p.name}: {e}", "red"))
                if e.kind == "download":
                    queue.append((p.name, p))
    except BaseException:
        for pl in plans:
            mgr.discard(pl)
        raise
    confirm_apply(mgr, plans)
    if queue and yn(f"{len(queue)} Datei(en) nacheinander im Browser laden?"):
        browser_queue(mgr, queue)


def pick(cands, what="Nummer (Enter = zurück): "):
    if not cands:
        print("Keine Treffer.")
        return None
    for i, c in enumerate(cands, 1):
        fv = {True: "ja", False: "nein", None: "?"}[c.has_forever]
        mark = paint(" [installiert]", "cyan") if c.installed else ""
        extra = f" – {c.author}" if c.author else ""
        dl = f" – {c.downloads:,} Downloads" if c.downloads else ""
        print(f"  {i:2}) {c.name}{extra}{dl} – Forever-Datei: {fv}{mark}")
    s = parse_selection(ask(what), len(cands))
    return cands[s[0] - 1] if s else None


def install_candidate(mgr, cand):
    try:
        plan = mgr.plan_candidate(cand)
    except ApiError as e:
        print(paint(f"{e}", "red"))
        if e.kind in ("nofile", "download") and yn("Im Browser herunterladen?"):
            browser_flow(mgr, mgr.browser_url(cand))
        return
    confirm_apply(mgr, [plan])


def forbidden_alternatives(mgr, q):
    print(paint("Suche ist für diesen API-Key nicht freigeschaltet.", "yellow"))
    print("Alternativen: [1] Beliebte Forever-Addons  [2] CurseForge-Projekt-ID eingeben  [3] Im Browser suchen")
    c = ask("Auswahl (Enter = zurück): ")
    if c == "1":
        cand = pick(mgr.featured())
        if cand:
            install_candidate(mgr, cand)
    elif c == "2":
        i = ask("Projekt-ID: ")
        if i.isdigit():
            cand = pick(mgr.resolve_input(i))
            if cand:
                install_candidate(mgr, cand)
        elif i:
            print("Ungültige ID.")
    elif c == "3":
        url = mgr.browser_url(None, q)
        print(f"Öffne {url}")
        mgr.open_browser(url)


def menu_new(mgr, pkgs):
    q = ask("Suchbegriff, CF-Projekt-ID, gh:owner/repo, URL, Zip-Pfad, 'p' = beliebte Addons (Enter = zurück): ")
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
            print(paint(f"Fehler: {e}", "red"))
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
        print("Keine nicht zugeordneten Ordner.")
        return
    for i, p in enumerate(un, 1):
        print(f"  {i}) {p.name}")
    sel = ask("Ordner (z. B. 1 3; Enter = zurück): ")
    s = parse_selection(sel, len(un)) if sel else None
    if sel and s is None:
        print("Ungültige Eingabe.")
    if not s:
        return
    folders = [un[i - 1].name for i in s]
    title = un[s[0] - 1].note or folders[0]
    q = ask(f"CF-Projekt-ID, gh:owner/repo oder CF-Suchbegriff [{title}]: ") or title
    repo = core.parse_github(q) if q.startswith("gh:") or "github.com/" in q else None
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
                    print(paint("Suche ist für diesen API-Key nicht freigeschaltet. "
                                "Gib die CF-Projekt-ID oder gh:owner/repo direkt ein.", "yellow"))
                else:
                    print(paint(f"Fehler: {e}", "red"))
                return
            if not cand:
                return
            mgr.assign_folders(folders, cand.name, cf_id=int(cand.ident))
    except (ValueError, OSError) as e:
        print(paint(f"Fehler: {e}", "red"))
        return
    print(f"Zugeordnet: {', '.join(folders)}")


def menu_browser(mgr, pkgs):
    s = ask("Nummer des Pakets (Enter = zurück): ")
    sel = parse_selection(s, len(pkgs)) if s else None
    if s and sel is None:
        print("Ungültige Eingabe.")
    if not sel:
        return
    p = pkgs[sel[0] - 1]
    if p.meta.get("unassigned"):
        print("Erst zuordnen (Taste z).")
        return
    browser_flow(mgr, mgr.browser_url(p), p.key)


def menu_key(mgr):
    print(f"Key-Status: {mgr.cf_key_state()}")
    v = ask("Neuer Key, '-' zum Löschen, Enter = unverändert: ")
    if v == "-":
        mgr.set_cf_key(None)
    elif v:
        mgr.set_cf_key(v)
    else:
        return False
    return True


def menu_restore(mgr):
    sets = mgr.list_backups()
    if not sets:
        print("Keine Sicherungen vorhanden.")
        return False
    for i, b in enumerate(sets, 1):
        print(f"  {i}) {b.name}: {', '.join(b.folders)}")
    s = ask("Sicherung wählen (Enter = zurück): ")
    sel = parse_selection(s, len(sets)) if s else None
    if s and sel is None:
        print("Ungültige Eingabe.")
    if not sel:
        return False
    b = sets[sel[0] - 1]
    if not b.folders or not yn(f"{len(b.folders)} Ordner wiederherstellen (aktuelle Versionen werden vorher gesichert)?"):
        return False
    if mgr.wow_running() and not yn(paint("WoW scheint zu laufen! Trotzdem fortfahren?", "yellow")):
        return False
    r = mgr.restore(b)
    print(paint(r.message, "green" if r.ok else "red"))
    return r.ok


def menu_uninstall(mgr, pkgs):
    s = ask("Nummern der zu deinstallierenden Pakete (z. B. 1 3 5-7, Enter = zurück): ")
    sel = parse_selection(s, len(pkgs)) if s else None
    if s and sel is None:
        print("Ungültige Eingabe.")
    if not sel:
        return False
    plans = [mgr.plan_uninstall(pkgs[i - 1]) for i in sel]
    for p in plans:
        print(paint(f"--- {p.name}", "bold"))
        print("  Ordner: " + (", ".join(p.folders) or "(keine)"))
        for w in p.warnings:
            print(paint("  ! " + w, "yellow"))
    print("Die Ordner werden in ein Backup verschoben (Menü w: Wiederherstellen). Einstellungen (SavedVariables/WTF) bleiben erhalten.")
    plans = [p for p in plans if p.folders]
    if not plans:
        return False
    if mgr.wow_running() and not yn(paint("WoW scheint zu laufen! Trotzdem fortfahren?", "yellow")):
        return False
    if not yn(f"{len(plans)} Paket(e) deinstallieren?"):
        print("Abgebrochen.")
        return False
    for r in mgr.uninstall(plans):
        print(paint(f"{r.name}: {r.message}", "green" if r.ok else "red")
              + (f"  (Sicherung: {r.backup_set})" if r.backup_set else ""))
    return True


def run(mgr):
    pkgs = refresh(mgr)
    while True:
        print()
        header(mgr)
        table(mgr, pkgs)
        print("\n[u] Updates  [n] Neu installieren  [z] Zuordnen  [b] Browser-Download  [k] CF-Key  "
              f"[e] Beta: {'an' if mgr.cfg['include_beta'] else 'aus'}  [r] Neu prüfen  [d] Deinstallieren  [w] Wiederherstellen  [q] Ende")
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
            elif c == "k":
                again = menu_key(mgr)
            elif c == "e":
                mgr.set_include_beta(not mgr.cfg["include_beta"])
                again = True
            elif c == "d":
                again = menu_uninstall(mgr, pkgs)
            elif c == "w":
                again = menu_restore(mgr)
            elif c:
                print("Unbekannte Eingabe.")
            if again:
                pkgs = refresh(mgr)
        except ApiError as e:
            print(paint(f"Fehler: {e}", "red"))
        except OSError as e:
            print(paint(f"Dateifehler: {e}", "red"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wow-forever-addon-manager",
                                 description="Addon-Manager für WoW: Forever (CurseForge/GitHub, mit Sicherungen).")
    ap.add_argument("--cli", action="store_true", help="Kommandozeile erzwingen (statt GUI)")
    ap.add_argument("--check", action="store_true", help="nur Tabelle ausgeben, nicht interaktiv")
    ap.add_argument("--addons-dir", metavar="PATH", help="AddOns-Ordner (nur für diesen Lauf, wird nicht gespeichert)")
    ap.add_argument("--version", action="version", version=f"%(prog)s {core.__version__}")
    args = ap.parse_args(argv)
    try:
        mgr = Manager(addons_dir=args.addons_dir, log=print)
        if mgr.needs_setup():
            if args.addons_dir:
                print(f"AddOns-Ordner nicht gefunden: {args.addons_dir}", file=sys.stderr)
                return 1
            if args.check or not sys.stdin.isatty():
                print("Kein AddOns-Ordner eingerichtet. Gefundene Kandidaten:")
                cands = mgr.find_installs()
                print_candidates(cands) if cands else print("  (keine)")
                print("Starte ohne --check zur Auswahl oder nutze --addons-dir PFAD.")
                return 1
            if not setup_flow(mgr):
                return 1
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
