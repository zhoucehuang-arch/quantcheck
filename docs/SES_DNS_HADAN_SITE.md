# SES DNS records for hadan.site

Add these records in Tencent Cloud DNSPod for zone: hadan.site

## Domain verification TXT
- Type: TXT
- Host/Name: _amazonses
- Value: 2nW9AfCbe/rFbyELiIvIDIEtYDxhZi39pelCHQo7I6M=
- TTL: 600

## DKIM CNAME records
- Type: CNAME
- Host/Name: tzavlsnlcwgdyrzputwsdub2rzosuazt._domainkey
- Value: tzavlsnlcwgdyrzputwsdub2rzosuazt.dkim.amazonses.com
- TTL: 600

- Type: CNAME
- Host/Name: xaiegjpii6xjhcdfzv7piu6orhl7zq6w._domainkey
- Value: xaiegjpii6xjhcdfzv7piu6orhl7zq6w.dkim.amazonses.com
- TTL: 600

- Type: CNAME
- Host/Name: gwyeuopngeudq2bryqvgcipzyeqtlkix._domainkey
- Value: gwyeuopngeudq2bryqvgcipzyeqtlkix.dkim.amazonses.com
- TTL: 600

## SPF TXT
If hadan.site is only used for SES mail sending, add:
- Type: TXT
- Host/Name: @
- Value: v=spf1 include:amazonses.com ~all
- TTL: 600

If you later use another mail service for the same domain, merge SPF into one TXT record instead of creating a second SPF record.

## DMARC TXT
Start relaxed for monitoring:
- Type: TXT
- Host/Name: _dmarc
- Value: v=DMARC1; p=none; rua=mailto:notify@hadan.site
- TTL: 600

After stable delivery, change p=none to p=quarantine or p=reject.
