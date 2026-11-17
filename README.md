# Tarihte Bugün – Otomatik Dünya Tarihi RSS

GitHub Pages + GitHub Actions ile çalışır; sunucu ve ücretli API gerekmez. Her gün Vikipedi'nin
**MediaWiki Action API**'sinden (`tr.wikipedia.org` ve `en.wikipedia.org` `/w/api.php`) o güne ait
olay, doğum ve ölümleri okur, her biri için Türkçe, Blogger uyumlu (H1'siz) tam makale üretir ve RSS'i yeniler.

* RSS: https://umutevicom-commits.github.io/tarih/rss.xml
* Aynı içerik: https://umutevicom-commits.github.io/tarih/feed
* Makale sayfaları: `/makale/<tarih>-<slug>.html`, site haritası: `/sitemap.xml`

## Kurulum (5 adım)

1. Bu klasörün içeriğini `umutevicom-commits/tarih` deposuna kopyalayın (mevcut dosyalarınızı **silmez/ezmez**:
   yalnızca `tarihrss/`, `tests/`, `data/`, `assets/kapak-varsayilan.svg`, `makale/`, `.github/workflows/tarih-rss.yml`
   ve üretilen `rss.xml`, `feed`, `sitemap.xml` eklenir). Depoda zaten `README.md`, `.gitignore` varsa birleştirin.
2. **Settings → Pages → Build and deployment**: Source = *Deploy from a branch*, Branch = `main` / `(root)`.
3. **Settings → Actions → General → Workflow permissions**: *Read and write permissions* seçin.
4. **Actions → "Günlük Tarihte Bugün RSS" → Run workflow** ile ilk çalıştırmayı elle yapın (isterseniz tarih/adet girin).
5. 1–2 dakika sonra `…/tarih/rss.xml` adresini açın. Sonrasında her gün 06:17 (TSİ) otomatik çalışır;
   14:47'deki ikinci çalışma yalnızca bir arıza olduysa eksik makaleleri tamamlar.

## Nasıl çalışır

| Adım | Ne yapar |
|---|---|
| Aday toplama | `18 Kasım` (tr) ve `November 18` (en) sayfalarının vikimetnini okur; Olaylar/Doğumlar/Ölümler ayrıştırılır |
| Seçim | Dönem, konu (savaş, bilim, siyaset, kültür, doğa) ve bölge çeşitliliği gözetilir; günde 3 makale (2 olay + 1 kişi, günlere göre dönüşümlü) |
| Doğrulama kapıları | Türkçe Vikipedi maddesi var mı, anlam ayrımı sayfası değil mi, yeterli uzunlukta mı, kapak görseli (≥700 px, bayrak/harita/logo değil) var mı |
| Makale | Kapak görseli → Kısa Özet → (maddenin TÜM metni:) Tarihî Arka Plan → Olayın Gelişimi → Önemli Kişiler → Dünya Tarihindeki Etkileri → Sonuç → Kaynaklar |
| Tekrar kontrolü | `data/index.json` içinde konu anahtarı + olay kimliği; yıllar arasında da aynı madde ikinci kez yayımlanmaz |
| Kalıcılık | `data/index.json` (+ `.bak`), gövdeler `data/content/*.html`; hepsi git'e işlenir (git geçmişi de yedektir) |
| Hata yönetimi | `maxlag`, 429/5xx'te üstel geri çekilme, ağ hatası yeniden denemesi; API tamamen kapalıysa mevcut RSS bozulmadan korunur ve iş "başarısız" görünür; görsel yoksa varsayılan kapak |

Başlıklar her koşulda ≤ 70 karakterdir (testle doğrulanır). RSS'te her öğe: `title`, `link`, `guid` (kalıcı),
`pubDate`, `description` (≤155 karakter meta açıklama), `category`, `media:content` ve `content:encoded` içinde **tam makale HTML'i**.

## Ayarlar (workflow `env:` veya ortam değişkeni)

`ARTICLES_PER_DAY` (3) · `FEED_ITEMS` (50) · `MAX_BODY_CHARS` (0 = sınırsız, maddenin tamamı; sınır koymak için karakter sayısı) · `SITE_URL` · `WIKI_CONTACT` (User-Agent'ta iletişim bilgisi)

## Yerelde deneme

```bash
python -m unittest discover -s tests          # ağsız testler (sahte API)
python -m tarihrss --date 2026-11-18 --count 3 # gerçek API ile üretim (internet gerekir)
```

## Bilmeniz gerekenler

* **Özgünlük:** Üretim sırasında LLM kullanılmaz (ücretsiz/sunucusuz kalması için). Metinler Türkçe Vikipedi
  maddelerinden derlenir; bu yüzden Google'da "özgün içerik" sayılmayabilir. Lisans gereği (CC BY-SA 4.0) her makalede
  kaynak ve lisans notu bulunur. Daha özgün metin isterseniz `article.py` çıktısı ücretsiz bir LLM katmanından geçirilebilir.
* **Olay cümlesi:** Yalnızca Türkçe gün sayfasındaki olaylar Türkçe cümleyle başlar. İngilizce gün sayfasındaki olaylar,
  yalnızca Türkçe karşılığı net bir "olay maddesi" ise (ör. *… Muharebesi*) kullanılır; çeviri uydurulmaz.
* **Bölge dengesi** anahtar sözcük sezgisine dayanır, kesin değildir.
* **Veri yoksa bölüm yok:** Maddede ilgili içerik bulunmazsa (ör. "Etkileri" bölümü) o başlık atlanır; dolgu metin yazılmaz.
* **`/feed` adresi** uzantısız bir dosyadır; GitHub Pages bunu `application/octet-stream` ile sunabilir. RSS okuyucular
  içeriği tanır, tarayıcı indirme önerebilir. Gerçek başlık/tür gerekirse `rss.xml` kullanın.
* **Blogger:** Blogger RSS'i doğrudan içe aktarmaz; `content:encoded` içindeki HTML'i kendi aktarım aracınızla ya da
  elle yazıya yapıştırarak kullanabilirsiniz (H1 içermez, görsel ve ALT hazırdır).
* Pages dal-kaynaklı değilse (Source = GitHub Actions) yayın adımı farklı olmalıdır; bu iş akışı dal-kaynaklı siteyi varsayar.
