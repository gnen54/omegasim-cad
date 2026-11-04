# Fusion-Add-In „Lenkeinschlag“

Legt in Fusion einen Knopf **Lenkeinschlag** an (Konstruktion → Volumenkörper → Prüfen und Dienstprogramme → Add-Ins).

- Findet alle Drehgelenke der Konstruktion
- Lenkregler −100 % (voll rechts) bis +100 % (voll links) mit Live-Vorschau
- Maximaler Einschlag je Rad getrennt für links und rechts, Drehrichtung umkehrbar, begrenzt auf ±30°
- **Pendeln**: Räder schwenken einmal voll nach links und rechts
- **Lenkfreiraum als Körper erzeugen**: vereinigt die Räder in allen Stellungen (Schritt 2°) zu einem Körper, der sich als Abzieh-Teil für Radhäuser eignet
- **Geradeaus stellen**

## Installieren

1. Ordner `LenkeinschlagAddIn` herunterladen.
2. In Fusion **Shift+S** → Reiter **Add-Ins** → grünes **+** → Ordner wählen.
3. Markieren, **Ausführen**, **Beim Start ausführen** anhaken.

Annahmen: Gelenkwert 0° = geradeaus; Gelenkgrenzen werden beachtet.

Lizenz: [MIT](../../LICENSE-MIT)
