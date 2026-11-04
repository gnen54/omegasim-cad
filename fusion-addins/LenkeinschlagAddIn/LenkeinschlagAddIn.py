# LenkeinschlagAddIn.py – Fusion-Add-In für OmegaSim
# Legt beim Start von Fusion einen Knopf „Lenkeinschlag“ in Konstruktion → Prüfen an.
# Bewegt die Vorderräder über ihre Drehgelenke (Revolute Joints) per Lenkwinkel,
# lässt sie zwischen vollem Einschlag links und rechts pendeln und kann den
# Raum, den die Räder dabei überstreichen, als eigenen Körper "Lenkfreiraum" anlegen.
#
# Annahmen:
#  * Jedes Vorderrad (oder der Lenkservo) hat ein Drehgelenk.
#  * Gelenkwert 0° = geradeaus.
#  * Positive Lenkung (+100 %) = Einschlag nach links.
# Interne Einheiten von Fusion: Länge cm, Winkel Bogenmaß.

import adsk.core, adsk.fusion, traceback, math

CMD_ID = 'omegasim_lenkeinschlag'
CMD_NAME = 'Lenkeinschlag (OmegaSim)'
KEIN = '– keins –'
AKTIONEN = ['Lenkwinkel einstellen', 'Pendeln (links ↔ rechts)', 'Lenkfreiraum als Körper erzeugen', 'Geradeaus stellen']

app = None
ui = None
handlers = []
gelenke = {}          # Anzeigename -> Gelenk
merk = {}             # letzte Eingaben innerhalb dieser Fusion-Sitzung


def _name(j):
    try:
        ctx = j.assemblyContext
        if ctx:
            return '%s  [%s]' % (j.name, ctx.fullPathName)
    except Exception:
        pass
    return j.name


def drehgelenke_sammeln(root):
    liste = []
    for attr in ('allJoints', 'allAsBuiltJoints'):
        try:
            for j in getattr(root, attr):
                liste.append(j)
        except Exception:
            pass
    if not liste:   # ältere Fusion-Fassungen ohne allJoints
        for j in root.joints:
            liste.append(j)
        for j in root.asBuiltJoints:
            liste.append(j)
        for occ in root.allOccurrences:
            for j in occ.component.joints:
                liste.append(j.createForAssemblyContext(occ))
            for j in occ.component.asBuiltJoints:
                liste.append(j.createForAssemblyContext(occ))
    erg = {}
    for j in liste:
        try:
            if j.jointMotion.jointType == adsk.fusion.JointTypes.RevoluteJointType:
                n = _name(j)
                while n in erg:
                    n += ' '
                erg[n] = j
        except Exception:
            pass
    return erg


def vorschlag(namen, woerter):
    for n in namen:
        l = n.lower()
        if any(w in l for w in woerter):
            return n
    return None


def winkel_fuer(s, max_links, max_rechts, umkehren):
    """s: -1 (voll rechts) … +1 (voll links). Ergebnis in Bogenmaß."""
    w = s * max_links if s >= 0 else s * max_rechts
    return -w if umkehren else w


GRENZE = math.radians(30)   # Gelenkgrenzen der Porsche-Vorderachse: ±30°


def setze(j, w):
    if j is not None:
        j.jointMotion.rotationValue = max(-GRENZE, min(GRENZE, w))


def werte(inputs):
    def v(i):
        return inputs.itemById(i).value
    a = inputs.itemById('gelenk_a').selectedItem.name
    b = inputs.itemById('gelenk_b').selectedItem.name
    return dict(
        ja=gelenke.get(a), jb=gelenke.get(b) if b != KEIN else None,
        a_l=v('a_links'), a_r=v('a_rechts'), a_u=v('a_umk'),
        b_l=v('b_links'), b_r=v('b_rechts'), b_u=v('b_umk'),
        s=inputs.itemById('lenkung').valueOne / 100.0,
        schritt=v('schritt'), dauer=v('dauer'),
        aktion=inputs.itemById('aktion').selectedItem.name,
        raeder=[inputs.itemById('raeder').selection(i).entity for i in range(inputs.itemById('raeder').selectionCount)])


def stelle(p, s):
    setze(p['ja'], winkel_fuer(s, p['a_l'], p['a_r'], p['a_u']))
    setze(p['jb'], winkel_fuer(s, p['b_l'], p['b_r'], p['b_u']))


def merken(inputs):
    for i in ('a_links', 'a_rechts', 'b_links', 'b_rechts', 'schritt', 'dauer'):
        merk[i] = inputs.itemById(i).value
    for i in ('a_umk', 'b_umk'):
        merk[i] = inputs.itemById(i).value
    merk['gelenk_a'] = inputs.itemById('gelenk_a').selectedItem.name
    merk['gelenk_b'] = inputs.itemById('gelenk_b').selectedItem.name


def pendeln(p):
    vp = app.activeViewport
    n = 40
    folge = [math.sin(2 * math.pi * k / n) for k in range(n + 1)]
    pause = max(p['dauer'], 0.5) / n
    import time
    for s in folge:
        stelle(p, s)
        vp.refresh()
        adsk.doEvents()
        time.sleep(pause)
    stelle(p, 0.0)
    vp.refresh()


def koerper_von(occ):
    """Alle B-Rep-Körper eines Bauteils samt Unterbauteilen (im Baugruppen-Kontext)."""
    k = list(occ.bRepBodies)
    for c in occ.childOccurrences:
        k += koerper_von(c)
    return k


def kopie_in_welt(tbm, body, occ):
    t = tbm.copy(body)
    # Je nach Fusion-Fassung liegt die Kopie schon im Baugruppen-Raum oder noch im Bauteil-Raum.
    a = body.boundingBox.minPoint
    b = t.boundingBox.minPoint
    if a.distanceTo(b) > 1e-5:
        tbm.transform(t, body.assemblyContext.transform2 if body.assemblyContext else occ.transform2)
    return t


def lenkfreiraum(p):
    if not p['raeder']:
        ui.messageBox('Bitte unter „Räder“ die Bauteile der Vorderräder auswählen.')
        return
    design = adsk.fusion.Design.cast(app.activeProduct)
    tbm = adsk.fusion.TemporaryBRepManager.get()
    max_w = max(p['a_l'], p['a_r'], p['b_l'], p['b_r'], 1e-6)
    n = max(2, int(math.ceil(max_w / max(p['schritt'], math.radians(0.5)))))
    stufen = [-1.0 + k / n for k in range(2 * n + 1)]
    huelle = None
    fort = ui.createProgressDialog()
    fort.show('Lenkfreiraum', 'Stellung %v von %m', 0, len(stufen), 0)
    for i, s in enumerate(stufen):
        stelle(p, s)
        adsk.doEvents()
        for occ in p['raeder']:
            for body in koerper_von(occ):
                t = kopie_in_welt(tbm, body, occ)
                if huelle is None:
                    huelle = t
                else:
                    tbm.booleanOperation(huelle, t, adsk.fusion.BooleanTypes.UnionBooleanType)
        fort.progressValue = i + 1
        if fort.wasCancelled:
            break
    fort.hide()
    stelle(p, 0.0)
    if huelle is None:
        ui.messageBox('Keine B-Rep-Körper gefunden. Netzkörper (Mesh) werden nicht unterstützt.')
        return
    root = design.rootComponent
    neu = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = neu.component
    comp.name = 'Lenkfreiraum'
    if design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
        bf = comp.features.baseFeatures.add()
        bf.startEdit()
        comp.bRepBodies.add(huelle, bf)
        bf.finishEdit()
    else:
        comp.bRepBodies.add(huelle)
    ui.messageBox('Lenkfreiraum angelegt (%d Stellungen).\n'
                  'Für Luft zur Karosserie den Körper z. B. mit „Fläche versetzen“ um 0,3–0,5 mm vergrößern,\n'
                  'dann als Werkzeug beim Kombinieren (Ausschneiden) verwenden oder als STL „Del-Lenkfreiraum“ exportieren.' % len(stufen))


class Erstellt(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            global gelenke
            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                ui.messageBox('Bitte zuerst eine Konstruktion öffnen (Arbeitsbereich KONSTRUKTION).')
                return
            gelenke = drehgelenke_sammeln(design.rootComponent)
            if not gelenke:
                ui.messageBox('In dieser Konstruktion gibt es keine Drehgelenke.\n'
                              'Bitte für jedes Vorderrad ein Drehgelenk um die Lenkachse anlegen (Zusammenfügen → Gelenk → Drehung).')
                return
            cmd = args.command
            cmd.isExecutedWhenPreEmpted = False
            inp = cmd.commandInputs
            namen = sorted(gelenke.keys())

            dd = inp.addDropDownCommandInput('aktion', 'Aktion', adsk.core.DropDownStyles.TextListDropDownStyle)
            for i, a in enumerate(AKTIONEN):
                dd.listItems.add(a, i == 0)

            sl = inp.addIntegerSliderCommandInput('lenkung', 'Lenkung (%)  rechts ← → links', -100, 100)
            sl.valueOne = 0

            ga = inp.addDropDownCommandInput('gelenk_a', 'Gelenk Rad links (oder Lenkservo)', adsk.core.DropDownStyles.TextListDropDownStyle)
            va = merk.get('gelenk_a') or vorschlag(namen, ('links', 'left', 'li', '_l')) or namen[0]
            for n in namen:
                ga.listItems.add(n, n == va)
            gb = inp.addDropDownCommandInput('gelenk_b', 'Gelenk Rad rechts', adsk.core.DropDownStyles.TextListDropDownStyle)
            vb = merk.get('gelenk_b') or vorschlag([n for n in namen if n != va], ('rechts', 'right', 're', '_r')) or KEIN
            gb.listItems.add(KEIN, vb == KEIN)
            for n in namen:
                gb.listItems.add(n, n == vb)

            ga_g = inp.addGroupCommandInput('grp_a', 'Rad links: maximaler Einschlag').children
            ga_g.addValueInput('a_links', 'beim Lenken nach links', 'deg', adsk.core.ValueInput.createByReal(merk.get('a_links', math.radians(30))))
            ga_g.addValueInput('a_rechts', 'beim Lenken nach rechts', 'deg', adsk.core.ValueInput.createByReal(merk.get('a_rechts', math.radians(30))))
            ga_g.addBoolValueInput('a_umk', 'Drehrichtung umkehren', True, '', merk.get('a_umk', False))
            gb_g = inp.addGroupCommandInput('grp_b', 'Rad rechts: maximaler Einschlag').children
            gb_g.addValueInput('b_links', 'beim Lenken nach links', 'deg', adsk.core.ValueInput.createByReal(merk.get('b_links', math.radians(30))))
            gb_g.addValueInput('b_rechts', 'beim Lenken nach rechts', 'deg', adsk.core.ValueInput.createByReal(merk.get('b_rechts', math.radians(30))))
            gb_g.addBoolValueInput('b_umk', 'Drehrichtung umkehren', True, '', merk.get('b_umk', False))

            gp = inp.addGroupCommandInput('grp_p', 'Pendeln und Lenkfreiraum').children
            gp.addValueInput('dauer', 'Dauer einer Pendelbewegung (s)', '', adsk.core.ValueInput.createByReal(merk.get('dauer', 3.0)))
            gp.addValueInput('schritt', 'Schrittweite Lenkfreiraum', 'deg', adsk.core.ValueInput.createByReal(merk.get('schritt', math.radians(2))))
            sel = gp.addSelectionInput('raeder', 'Räder (für Lenkfreiraum)', 'Bauteile der Vorderräder wählen')
            sel.addSelectionFilter('Occurrences')
            sel.setSelectionLimits(0, 0)

            h1 = Vorschau(); cmd.executePreview.add(h1); handlers.append(h1)
            h2 = Ausfuehren(); cmd.execute.add(h2); handlers.append(h2)
            h3 = Ende(); cmd.destroy.add(h3); handlers.append(h3)
        except Exception:
            ui.messageBox('Fehler:\n' + traceback.format_exc())


class Vorschau(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inp = args.command.commandInputs
            p = werte(inp)
            if p['aktion'] == AKTIONEN[0]:
                stelle(p, p['s'])
                args.isValidResult = True
            elif p['aktion'] == AKTIONEN[3]:
                stelle(p, 0.0)
                args.isValidResult = True
        except Exception:
            ui.messageBox('Fehler in der Vorschau:\n' + traceback.format_exc())


class Ausfuehren(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inp = args.command.commandInputs
            merken(inp)
            p = werte(inp)
            if p['aktion'] == AKTIONEN[0]:
                stelle(p, p['s'])
            elif p['aktion'] == AKTIONEN[1]:
                pendeln(p)
            elif p['aktion'] == AKTIONEN[2]:
                lenkfreiraum(p)
            else:
                stelle(p, 0.0)
        except Exception:
            ui.messageBox('Fehler:\n' + traceback.format_exc())


class Ende(adsk.core.CommandEventHandler):
    def notify(self, args):
        pass   # Add-In bleibt geladen


PANELS = ['InspectPanel', 'SolidScriptsAddinsPanel']   # Prüfen; ersatzweise Dienstprogramme → Add-Ins


def run(context):
    global app, ui
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        import os
        res = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources')
        d = ui.commandDefinitions.itemById(CMD_ID)
        if d:
            d.deleteMe()
        d = ui.commandDefinitions.addButtonDefinition(
            CMD_ID, 'Lenkeinschlag',
            'Vorderräder per Lenkwinkel bewegen, pendeln lassen und den Lenkfreiraum als Körper erzeugen (OmegaSim)', res)
        h = Erstellt()
        d.commandCreated.add(h)
        handlers.append(h)
        gefunden = []
        for pid in PANELS:
            panel = ui.allToolbarPanels.itemById(pid)
            if panel:
                c = panel.controls.itemById(CMD_ID)
                if c:
                    c.deleteMe()
                c = panel.controls.addCommand(d)
                c.isPromoted = True
                c.isPromotedByDefault = True
                gefunden.append(panel.name)
        if not context.get('IsApplicationStartup', True):
            ui.messageBox('Lenkeinschlag ist geladen.\nKnopf zu finden unter: ' + (' und '.join(gefunden) or 'keiner Gruppe (bitte melden)'))
    except Exception:
        if ui:
            ui.messageBox('Lenkeinschlag-Add-In konnte nicht starten:\n' + traceback.format_exc())


def stop(context):
    try:
        for pid in PANELS:
            panel = ui.allToolbarPanels.itemById(pid)
            if panel:
                c = panel.controls.itemById(CMD_ID)
                if c:
                    c.deleteMe()
        d = ui.commandDefinitions.itemById(CMD_ID)
        if d:
            d.deleteMe()
    except Exception:
        if ui:
            ui.messageBox('Fehler beim Beenden:\n' + traceback.format_exc())
