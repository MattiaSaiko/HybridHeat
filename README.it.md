<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/hybrid_heat/brand/dark_logo.png">
    <img src="custom_components/hybrid_heat/brand/logo.png" alt="Hybrid Heat, riscaldamento intelligente stanza per stanza per Home Assistant" width="420">
  </picture>
</p>

# Hybrid Heat: riscaldamento intelligente per zone in Home Assistant (valvole termostatiche, pompa di calore, solare termico, fotovoltaico)

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.2.0%2B-blue.svg)](https://www.home-assistant.io/)
[![Release](https://img.shields.io/github/v/release/MattiaSaiko/HybridHeat)](https://github.com/MattiaSaiko/HybridHeat/releases)
[![Validate](https://github.com/MattiaSaiko/HybridHeat/actions/workflows/validate.yml/badge.svg)](https://github.com/MattiaSaiko/HybridHeat/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PayPal](https://img.shields.io/badge/Donate-PayPal-00457C.svg?logo=paypal&logoColor=white)](https://paypal.me/Saikoadv)

🇬🇧 [English](README.md) · 🇮🇹 Italiano

**Hybrid Heat** è un'integrazione personalizzata per [Home Assistant](https://www.home-assistant.io/) (si installa con [HACS](https://hacs.xyz/)) che scalda ogni stanza con il dispositivo giusto al momento giusto, per ridurre la bolletta del riscaldamento. È un termostato intelligente multizona che coordina **valvole termostatiche per termosifoni**, **condizionatori e pompe di calore** in riscaldamento e, se presente, la **caldaia a gas**. Usa prima l'energia gratuita: **solare termico** e **surplus fotovoltaico**, anche con la batteria di accumulo.

Si configura tutta dall'interfaccia di Home Assistant, senza YAML. Crei le **zone** (una stanza o un gruppo di stanze) e Hybrid Heat decide quale dispositivo scalda ogni zona e a quale temperatura.

[![Apri la tua istanza di Home Assistant e questo repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=MattiaSaiko&repository=HybridHeat&category=integration)

## Cosa ottieni

- **Riscaldamento per zone.** Ogni zona ha il suo programma e le sue temperature comfort, eco e antigelo.
- **Il dispositivo giusto per ogni compito.** I condizionatori portano in fretta la stanza in temperatura; le valvole dei termosifoni la mantengono in modo efficiente.
- **Prima l'energia gratuita.** Con l'accumulo solare termico caldo i termosifoni lavorano col sole e la caldaia resta spenta. Con il surplus fotovoltaico (conta anche la carica di una batteria domestica) lavorano i condizionatori.
- **Caldaia facoltativa.** Si accende solo quando le valvole di una zona chiedono calore.
- **Programmi flessibili.** Fasce comfort per feriali e weekend, oppure qualsiasi `schedule` o calendario di Home Assistant. Il preriscaldamento impara quanto è veloce a scaldarsi ogni stanza.
- **Presenza e finestre.** Eco quando non c'è nessuno in casa, antigelo con la finestra aperta.
- **Decisioni leggibili.** Ogni zona mostra la fase in corso e il motivo.
- **Un termostato standard per ogni zona**, per la card termostato, gli assistenti vocali e le automazioni.
- **Niente prezzi, niente cloud.** Usa solo i tuoi sensori. Inglese e italiano inclusi.

## Come decide

| Situazione | Cosa fa Hybrid Heat |
|---|---|
| Stanza molto sotto la temperatura comfort | Il condizionatore sale di temperatura (*preriscaldamento*) |
| Stanza vicina alla temperatura comfort | Le valvole la mantengono (*mantenimento*) |
| Accumulo solare termico caldo | I termosifoni lavorano col sole, la caldaia resta spenta |
| Surplus fotovoltaico | I condizionatori lavorano con il surplus |
| Molto freddo fuori | Valvole al posto dei condizionatori |
| Finestra aperta da più di 2 minuti | Antigelo |
| Nessuno in casa (zona in Auto) | Temperatura eco |

Quando sono disponibili entrambe le fonti gratuite, vince il solare termico se è abbastanza caldo per ciò che serve alla stanza.

## Requisiti

- Home Assistant **2026.2.0** o successivo, impostato in **gradi Celsius**.
- Per ogni zona, almeno una valvola termostatica o un condizionatore (con modalità `heat`), esposti come entità `climate` (Zigbee2MQTT, ZHA, Tado, Daikin, l'integrazione del produttore, …).
- Tutto il resto è facoltativo: sensori di temperatura e finestre, temperatura esterna, temperatura dell'accumulo solare, potenza di rete per il surplus fotovoltaico, una batteria domestica, un interruttore per la caldaia, entità `person`.

## Installazione

**Con HACS:** apri HACS, menu (⋮) → **Repository personalizzati**, aggiungi `https://github.com/MattiaSaiko/HybridHeat` come **Integrazione**, scarica **Hybrid Heat** e riavvia Home Assistant.

**Manuale:** copia `custom_components/hybrid_heat` nella cartella `config/custom_components` e riavvia.

Poi vai in **Impostazioni → Dispositivi e servizi → Aggiungi integrazione** e scegli **Hybrid Heat**.

## Configurazione

1. **Fonti comuni a tutta la casa** (tutte facoltative): temperatura esterna, temperatura dell'accumulo solare, potenza di rete (un solo sensore con segno, oppure due sensori separati per immissione e prelievo), batteria domestica, interruttore caldaia, persone.
2. **Zone**: dalla pagina dell'integrazione scegli **Aggiungi zona**, poi indica climatizzatori, valvole, sensori di temperatura, sensori finestra e programma della zona. Il programma può essere quello interno (fasce comfort per feriali e weekend, fino a 3 ciascuno), un `schedule` o un calendario esterno, oppure nessuno.
3. **Accendi.** Hybrid Heat parte disabilitato e non tocca i tuoi dispositivi. Controlla temperature e modalità, poi accendi **Abilitato**.

Puoi cambiare fonti e zone in seguito dalla pagina dell'integrazione (⋮ → **Riconfigura**).

## Entità

Per una zona chiamata *Living room* (gli ID sono quelli predefiniti in inglese):

| Entità | Cos'è |
|---|---|
| `climate.living_room` | Il termostato della zona: acceso/spento, preset Auto, Comfort, Eco e Antigelo, temperatura attuale, stato di riscaldamento. Gli attributi `phase` e `reason` spiegano la decisione. |
| `select.living_room_mode` | `auto`, `comfort`, `eco`, `antifreeze` (mantiene la temperatura antigelo) oppure `off` (tiene spenti i dispositivi della zona) |
| `number.living_room_comfort_temperature` (e così per `eco` e `antifreeze`) | Le temperature della zona, 20 / 17 / 7 °C di default |
| `sensor.living_room_phase` | `off`, `antifreeze`, `window_open`, `eco`, `preheating` o `maintenance`, con gli attributi `reason`, `actuator` e `actuator_reason` |
| `binary_sensor.living_room_heat_request` | Acceso quando la zona chiede calore |

Per tutta la casa: `switch.hybrid_heat_enabled` (spento di default) e `sensor.hybrid_heat_active_source` (`solar_thermal`, `photovoltaic` o `none`). Soglie, ritardi e le altre impostazioni sono entità `number` nella pagina del dispositivo dell'integrazione.

## Da sapere

- **Disabilitato significa mani libere.** Con **Abilitato** spento, Hybrid Heat non invia nessun comando, nemmeno l'antigelo, quindi comandi tu i tuoi dispositivi. Quando lo spegni, porta su off una volta sola valvole, condizionatori in riscaldamento e caldaia. Per la protezione dal gelo tieni **Abilitato** acceso e metti la zona in **Antigelo**.
- **Caldaia.** Se dai a Hybrid Heat un interruttore per la caldaia, fai in modo che sia l'unico a comandarla. Da abilitato la accende anche per proteggere dal gelo le zone in Antigelo (o con la finestra aperta).
- **Rimozione.** I dispositivi restano esattamente come sono.
- **Solo riscaldamento.** I condizionatori che raffrescano, o che sono in un'altra modalità, non vengono mai toccati. Le temperature sono in °C e c'è un'istanza per Home Assistant.
- **Sensori non disponibili.** Se un sensore non risponde, Hybrid Heat continua a funzionare con ciò che ha.

## Supporto

Se Hybrid Heat ti fa risparmiare sul riscaldamento e vuoi dire grazie, puoi offrirmi un caffè:

<div align="center">

[![PayPal](https://img.shields.io/badge/Donate-PayPal-00457C.svg?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/Saikoadv)

</div>

Una ⭐ al repository aiuta altre persone a trovarlo. Segnalazioni e idee sono benvenute nelle [issue](https://github.com/MattiaSaiko/HybridHeat/issues), in italiano o in inglese. Per aggiungere una lingua, copia `custom_components/hybrid_heat/translations/en.json` in `<lingua>.json`, traduci i valori e apri una pull request.

## Licenza

Rilasciato con [licenza MIT](LICENSE).
