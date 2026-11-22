(() => {
  const en = {
    "Zum Inhalt":"Skip to content","Sprache":"Language","Verwaltung":"Administration","Gemeinsame":"Shared","Fotoalben":"photo albums",
    "Gemeinsame Fotoalben":"Shared photo albums","Wähle dein Album, um Fotos und Videos anzusehen oder hochzuladen.":"Choose an album to view or upload photos and videos.",
    "Alben":"Albums","Alle Alben":"All albums","Abmelden":"Sign out","Per QR-Code öffnen":"Open by QR code",
    "Mit der Handykamera scannen und ein Album wählen.":"Scan with your phone camera and choose an album.","Startseite öffnen":"Open home page",
    "Adminpasswort":"Admin password","Albumpasswort":"Album password","Anzeigen":"Show","Anmelden":"Sign in","Album öffnen":"Open album",
    "Fotos hinzufügen":"Add photos","Zur Galerie ↓":"Go to gallery ↓","Dein Name":"Your name","(optional)":"(optional)","Name im Album":"Name in album",
    "Fotos & Videos wählen":"Choose photos & videos","Kamera öffnen":"Open camera","Fehlgeschlagene erneut versuchen":"Retry failed uploads","Bestätigung vorlesen":"Read confirmation aloud",
    "Galerie":"Gallery","Aktualisieren":"Refresh","Suche":"Search","Name oder Datei":"Name or file","Person":"Person","Alle Personen":"All people",
    "Typ":"Type","Fotos & Videos":"Photos & videos","Nur Fotos":"Photos only","Nur Videos":"Videos only","Sortieren":"Sort","Neueste Uploads":"Newest uploads",
    "Älteste Uploads":"Oldest uploads","Aufnahmedatum":"Date taken","Beliebteste":"Most popular","Ansicht":"View","Kacheln":"Tiles","Zeitstrahl":"Timeline","Karte":"Map",
    "Alle wählen":"Select all","Auswahl als ZIP":"Selection as ZIP","Alle als ZIP":"All as ZIP","Diashow":"Slideshow","Galerie wird geladen …":"Loading gallery …",
    "Weitere Dateien anzeigen":"Show more files","Schließen":"Close","Zurück":"Previous","Favorit":"Favorite","Original laden":"Download original","Weiter":"Next",
    "Kommentare":"Comments","Kommentar":"Comment","Schreibe etwas Nettes …":"Write something nice …","Absenden":"Send",
    "Alben verwalten":"Manage albums","Alben suchen":"Search albums","Albumname":"Album name","Name":"Name","Dateien":"Files","Speicherbedarf":"Storage used",
    "Öffentliche Adresse & QR-Codes":"Public address & QR codes","Funnel- oder HTTPS-Adresse":"Funnel or HTTPS address","Adresse speichern":"Save address","Adresse testen":"Test address",
    "Sicherheit, Funnel & Updates":"Security, Funnel & updates","Update-Befehl":"Update command","Befehl kopieren":"Copy command","Neu prüfen":"Check again",
    "Album anlegen":"Create album","Albumadresse":"Album URL","Beschreibung":"Description","Anlegen":"Create","Sicherung & Pflege":"Backup & maintenance",
    "Täglich auf zweiten Speicher sichern":"Back up to secondary storage daily","Backup herunterladen":"Download backup","Verwaiste Vorschauen entfernen":"Remove orphaned previews",
    "Neues Passwort":"New password","Passwort speichern":"Save password","Datum":"Date","Farbe":"Colour","Grün":"Green","Blau":"Blue","Rosa":"Rose","Gold":"Gold",
    "Titelbild":"Cover image","Neues Albumpasswort":"New album password","Gästelink ohne Passwort freigeben":"Enable guest link without password",
    "Gäste dürfen hochladen":"Guests may upload","Gäste dürfen die Galerie sehen":"Guests may view the gallery","Gäste dürfen herunterladen":"Guests may download",
    "GPS-Orte in der Galerie anzeigen":"Show GPS locations in gallery","Gäste dürfen Favoriten markieren":"Guests may mark favorites","Gäste dürfen kommentieren":"Guests may comment",
    "Gästelink gültig bis":"Guest link valid until","Speichern":"Save","Gästelink öffnen":"Open guest link","Gäste-QR anzeigen":"Show guest QR","Dateien verwalten":"Manage files",
    "Dateien anzeigen":"Show files","Papierkorb anzeigen":"Show trash","Archivieren":"Archive","Wiederherstellen":"Restore"
  };
  const back = Object.fromEntries(Object.entries(en).map(([de, value]) => [value, de]));
  let lang = new URLSearchParams(location.search).get("lang") || localStorage.getItem("foto-language") || "de";
  if (!['de','en'].includes(lang)) lang = 'de';
  function changeText(value, table) { const key=value.trim(); return key && table[key] ? value.replace(key, table[key]) : value; }
  function translate(root, table) {
    if (root.nodeType === Node.TEXT_NODE) { root.nodeValue=changeText(root.nodeValue, table); return; }
    if (![Node.ELEMENT_NODE,Node.DOCUMENT_NODE].includes(root.nodeType)) return;
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT); while(walker.nextNode()) walker.currentNode.nodeValue=changeText(walker.currentNode.nodeValue,table);
    if (root.querySelectorAll) for (const node of root.querySelectorAll('[placeholder],[aria-label],[title]')) for (const attr of ['placeholder','aria-label','title']) if(node.hasAttribute(attr)) node.setAttribute(attr,changeText(node.getAttribute(attr),table));
  }
  function apply(next) {
    const old=document.documentElement.lang==='en'?'en':'de'; if(old!==next) translate(document,next==='en'?en:back);
    lang=next; document.documentElement.lang=next; localStorage.setItem('foto-language',next); const picker=document.getElementById('language'); if(picker) picker.value=next;
  }
  document.addEventListener('DOMContentLoaded',()=>{ apply(lang); const picker=document.getElementById('language'); if(picker) picker.onchange=()=>apply(picker.value);
    new MutationObserver(records=>{if(lang==='en') for(const record of records) for(const node of record.addedNodes) translate(node,en);}).observe(document.body,{childList:true,subtree:true}); });
})();
