# Kiswahili wording: native-speaker review

For a native Kiswahili speaker, ideally one familiar with M-Pesa and community-agent language in Kenya. The Kiswahili below was written by the development team and has **not** been reviewed by a native speaker. It must be reviewed before any real beneficiary sees it.

Generated from the code (`backend/app/services/messaging/i18n.py`, `backend/app/services/ai/fallback.py`, `backend/app/services/ai/guardrails.py`). Send corrections as a table (key, corrected Kiswahili) and the development team will apply them; the tests check that each screen still fits a feature phone (182 characters, GSM 7-bit).

## What to check

1. **Money and status meaning (priority 1).** A beneficiary must never read a status as "paid" unless it is `succeeded`. Check that `approved_for_submission`, `submitted` and `pending_confirmation` do not sound like the money has arrived.
2. **PIN and security (priority 1).** The PIN, lockout, "changed phone or SIM" and "not verified" messages must be unambiguous, and must never ask anyone to share a PIN.
3. **Plain, everyday register (priority 2).** Short words a feature-phone user understands; no Sheng unless you recommend it.
4. **The AI guardrail word list (priority 1, last section).** Words that would claim money moved or something was approved. Add any common phrasing the list misses.

`{name}`-style placeholders are filled in by the system; keep them, and keep `0` (back) / `00` (home) and digits as they are.

## 1. Payout status labels (USSD, SMS, web)

| Status | English | Kiswahili | Priority |
|---|---|---|---|
| `requested` | Requested, waiting for review | Yameombwa, yanasubiri ukaguzi | 1 |
| `under_review` | Under review | Yanakaguliwa | 1 |
| `rejected` | Not approved. Contact your agent | Hayakuidhinishwa. Wasiliana na wakala wako | 1 |
| `approved_for_submission` | Approved, being prepared | Yameidhinishwa, yanaandaliwa | 1 |
| `submitted` | Sent to the mobile money provider, awaiting confirmation | Yametumwa kwa mtoa huduma, yanasubiri uthibitisho | 1 |
| `pending_confirmation` | Awaiting confirmation. Do not request again | Yanasubiri uthibitisho. Usiombe tena | 1 |
| `succeeded` | Paid to your mobile money account | Yamelipwa kwenye akaunti yako ya pesa kwa simu | 1 (only state that may say paid) |
| `failed` | Not completed. Your agent will help you | Hayakukamilika. Wakala wako atakusaidia | 1 |
| `cancelled` | Cancelled | Yameghairiwa | 1 |
| (unknown) | Status unavailable. Contact your agent | Hali haipatikani. Wasiliana na wakala | 1 |

## 2. Campaign status labels

| Status | English | Kiswahili | Priority |
|---|---|---|---|
| `draft` | Draft | Rasimu | 2 |
| `submitted` | In review | Inakaguliwa | 2 |
| `published` | Live | Iko hewani | 2 |
| `closed` | Closed | Imefungwa | 2 |

## 3. USSD screens and SMS messages

| Key | English | Kiswahili | Priority |
|---|---|---|---|
| `campaign_status` | {title}<br>Status: {status}<br>Raised: {raised} of {goal} | {title}<br>Hali: {status}<br>Imechangiwa: {raised} kati ya {goal} | 1 |
| `donate_info` | Donors give online with PayPal at {url}. Share your campaign link. FundBridge never asks you to send money to receive donations. | Wachangiaji hutoa kwa PayPal: {url}. Shiriki kiungo cha kampeni yako. FundBridge haitakuomba kutuma pesa ili upokee michango. | 1 |
| `help_sim` | Request received. Ref {ref}. An agent will verify your identity before any phone or payout details change. | Ombi limepokelewa. Kumb {ref}. Wakala atathibitisha utambulisho wako kabla ya kubadilisha taarifa za simu au malipo. | 1 |
| `no_payouts` | No payout requests yet. | Bado hakuna ombi la malipo. | 1 |
| `not_linked` | This number is not linked to a FundBridge beneficiary. Contact your community agent or choose 5 for help. | Nambari hii haijaunganishwa na mnufaika wa FundBridge. Wasiliana na wakala wako au chagua 5 kwa msaada. | 1 |
| `not_verified` | This number is waiting for verification by FundBridge. Contact your community agent or choose 5 for help. | Nambari hii inasubiri kuthibitishwa na FundBridge. Wasiliana na wakala wako au chagua 5 kwa msaada. | 1 |
| `notify_donation` | FundBridge: {title} received a confirmed donation of {amount}. Total raised: {raised}. | FundBridge: {title} imepokea mchango uliothibitishwa wa {amount}. Jumla: {raised}. | 1 |
| `notify_payout` | FundBridge: payout of {amount}: {status}. Dial {ussd} for details. | FundBridge: malipo ya {amount}: {status}. Piga {ussd} kwa maelezo. | 1 |
| `payout_status` | Payout {amount}<br>Status: {status}<br>Updated: {date} | Malipo {amount}<br>Hali: {status}<br>Yamesasishwa: {date} | 1 |
| `pin_confirm` | Enter the same PIN again: | Weka PIN hiyo tena: | 1 |
| `pin_create` | Create a 4-digit PIN to protect your payout information: | Unda PIN ya tarakimu 4 kulinda taarifa za malipo yako: | 1 |
| `pin_enter` | Enter your 4-digit FundBridge PIN: | Weka PIN yako ya FundBridge ya tarakimu 4: | 1 |
| `pin_invalid` | Wrong PIN. {left} attempt(s) left. | PIN si sahihi. Majaribio {left} yamebaki. | 1 |
| `pin_locked` | Too many wrong PINs. Try again in {minutes} minutes or contact your agent. | PIN zisizo sahihi mara nyingi. Jaribu tena baada ya dakika {minutes} au wasiliana na wakala wako. | 1 |
| `pin_mismatch` | The PINs did not match. Please dial again. | PIN hazikulingana. Tafadhali piga tena. | 1 |
| `pin_weak` | That PIN is too easy to guess. Please dial again and choose another. | PIN hiyo ni rahisi kukisia. Piga tena uchague nyingine. | 1 |
| `sms_payout_redirect` | FundBridge: for your security, payout status is shown only after PIN entry. Dial {ussd}. | FundBridge: kwa usalama wako, hali ya malipo huonyeshwa baada ya kuweka PIN. Piga {ussd}. | 1 |
| `sms_status` | FundBridge: {lines} | FundBridge: {lines} | 1 |
| `sms_stop` | FundBridge: you will not receive updates. Send START to resume. | FundBridge: hutapokea taarifa tena. Tuma START kuendelea. | 1 |
| `choose_campaign` | Choose a campaign: | Chagua kampeni: | 2 |
| `help_menu` | Help<br>1. Ask an agent to call me<br>2. Report a problem<br>3. I changed my phone or SIM | Msaada<br>1. Wakala anipigie<br>2. Ripoti tatizo<br>3. Nimebadilisha simu au laini | 2 |
| `help_opened` | Request received. Ref {ref}. An agent will contact you. | Ombi limepokelewa. Kumb {ref}. Wakala atawasiliana nawe. | 2 |
| `invalid` | Invalid choice. Please dial again. | Chaguo si sahihi. Tafadhali piga tena. | 2 |
| `language_menu` | Choose language / Chagua lugha<br>1. English<br>2. Kiswahili | Choose language / Chagua lugha<br>1. English<br>2. Kiswahili | 2 |
| `language_set` | Language set to English. | Lugha imewekwa: Kiswahili. | 2 |
| `main_menu` | FundBridge<br>1. My campaign<br>2. My payout status<br>3. Find a campaign<br>4. How donors give<br>5. Get help<br>6. Language/Lugha | FundBridge<br>1. Kampeni yangu<br>2. Hali ya malipo<br>3. Tafuta kampeni<br>4. Jinsi ya kuchangia<br>5. Msaada<br>6. Language/Lugha | 2 |
| `no_campaigns` | No campaigns are linked to your number yet. | Hakuna kampeni iliyounganishwa na nambari yako bado. | 2 |
| `notify_published` | FundBridge: your campaign {title} is now live. Share: {url} | FundBridge: kampeni yako {title} iko hewani sasa. Shiriki: {url} | 2 |
| `search_none` | No live campaigns match '{query}'. | Hakuna kampeni hai inayolingana na '{query}'. | 2 |
| `search_prompt` | Enter a word to search, e.g. school or clinic: | Andika neno la kutafuta, mfano shule au kliniki: | 2 |
| `search_results` | {lines}<br>Donate online: {url} | {lines}<br>Changia mtandaoni: {url} | 2 |
| `sms_assistant` | FundBridge (auto-reply): {reply} Send HELP for the menu. | FundBridge (jibu la kiotomatiki): {reply} Tuma MSAADA kwa menyu. | 2 |
| `sms_find_results` | FundBridge: {lines} Donate: {url} | FundBridge: {lines} Changia: {url} | 2 |
| `sms_find_usage` | FundBridge: send FIND and a word, e.g. FIND school | FundBridge: tuma TAFUTA na neno, mfano TAFUTA shule | 2 |
| `sms_help` | FundBridge: STATUS - campaign status. FIND <word> - search. AGENT - request a call. LANG SW - Kiswahili. Payout status: dial {ussd}. | FundBridge: HALI - hali ya kampeni. TAFUTA <neno> - tafuta. WAKALA - omba kupigiwa. LUGHA EN - English. Hali ya malipo: piga {ussd}. | 2 |
| `sms_start` | FundBridge: updates resumed. Send HELP for options. | FundBridge: taarifa zimerejeshwa. Tuma MSAADA kwa machaguo. | 2 |
| `unavailable` | Service temporarily unavailable. Please try again later. | Huduma haipatikani kwa sasa. Tafadhali jaribu tena baadaye. | 2 |

## 4. Assistant replies used when AI is unavailable

| Topic | English | Kiswahili | Priority |
|---|---|---|---|
| `security` | Please contact your community agent now. For your safety, any change to your phone or payout number needs an identity check before it takes effect. | Tafadhali wasiliana na wakala wako wa jamii sasa. Kwa usalama wako, kubadilisha nambari ya simu au ya malipo kunahitaji uthibitisho wa utambulisho kwanza. | 1 |
| `payout` | I cannot see your balance or payouts. Open Payout status for the confirmed details. If a payout says 'awaiting confirmation', please wait and do not request it again. | Siwezi kuona salio au malipo yako. Fungua Hali ya malipo kwa taarifa zilizothibitishwa. Ikiwa malipo yanasema 'yanasubiri uthibitisho', subiri na usiombe tena. | 1 |
| `fees` | Fees are shown to donors before they pay and in your campaign's payout breakdown. Open your campaign to see the confirmed amounts. | Ada huonyeshwa kwa wachangiaji kabla ya kulipa na kwenye muhtasari wa malipo wa kampeni yako. | 2 |
| `donation` | Donors give online through PayPal. A donation counts only after the payment provider confirms it. Share your campaign link so people can donate. | Wachangiaji hutoa mtandaoni kupitia PayPal. Mchango huhesabiwa tu baada ya mtoa huduma wa malipo kuuthibitisha. Shiriki kiungo cha kampeni yako. | 1 |
| `verify` | To verify your phone, request a code from the app or your community agent and enter it within 10 minutes. Never share the code with anyone. | Ili kuthibitisha simu yako, omba nambari kupitia programu au wakala wako na uiweke ndani ya dakika 10. Usimpe mtu yeyote nambari hiyo. | 1 |
| `campaign` | Your campaign is reviewed by FundBridge before it is published. You can check its status in My campaigns or by dialing the FundBridge USSD code. | Kampeni yako hukaguliwa na FundBridge kabla ya kuchapishwa. Angalia hali yake kwenye Kampeni zangu au kwa kupiga msimbo wa USSD wa FundBridge. | 2 |
| `general` | I can explain how campaigns, donations, payouts and fees work. For your own balance or payout, open the status pages or contact your community agent. | Ninaweza kueleza jinsi kampeni, michango, malipo na ada zinavyofanya kazi. Kwa salio au malipo yako, fungua kurasa za hali au wasiliana na wakala wako. | 2 |

## 5. Campaign draft template (used when AI is unavailable)

| Part | English | Kiswahili | Priority |
|---|---|---|---|
| Title | Help {who} with {category} | Msaidie {who} kupata {category} | 2 |
| Default `{who}` | a community member | mwanajamii | 2 |
| Goal line | The goal of this campaign is {amount} {currency}. | Lengo la kampeni hii ni {amount} {currency}. | 2 |
| Closing | Every donation goes through FundBridge, and FundBridge reviews each payout before releasing it to the beneficiary. | Michango yote hupitia FundBridge. Fedha hutolewa kwa mnufaika baada tu ya ukaguzi wa malipo wa FundBridge. | 1 |
| Category `medical` | medical care | matibabu | 2 |
| Category `education` | education | elimu | 2 |
| Category `emergency` | emergency recovery | kujikwamua baada ya dharura | 2 |
| Category `community` | a community project | mradi wa jamii | 2 |
| Category `agriculture` | farming | kilimo | 2 |
| Category `small_business` | a small business | biashara ndogo | 2 |
| Category `housing` | safe housing | makazi salama | 2 |
| Category `water_sanitation` | clean water | maji safi | 2 |
| Category `other` | an urgent need | hitaji la dharura | 2 |

## 6. AI guardrail: Kiswahili claims the assistant must never make

When an AI reply contains one of these, it is replaced with a safe message (assistant) or flagged for the human editor (drafts). Current coverage, from `guardrails.py`:

- Any noun class + `-me-` + one of: `tumwa` (sent), `tumiwa` (sent to), `lipwa` (paid), `idhinishwa` (approved), `thibitishwa` (confirmed/verified), `pokelewa` (received), `kamilika` (completed), `ingizwa` (deposited), `wekwa` (deposited). Examples: *pesa imetumwa*, *pesa zimetumwa*, *malipo yamelipwa*, *mchango umethibitishwa*, *wamelipwa*.
- `umepokea`, `mmepokea`, `amepokea` (you / you all / he or she have received).

Please list any other everyday ways to say "the money has been sent / paid / approved / received / is on its way" (including M-Pesa phrasing such as *umetumiwa*, or near-future forms such as *itafika leo*) and any "FundBridge has verified / guarantees" phrasing. Also flag any word above that would block normal, safe sentences.

