import { Document, Link, Page, StyleSheet, Text, View } from '@react-pdf/renderer';

import type { PdfActivityLink, PdfBlockData, PdfDaySection, PdfHotelLink, TripPdfData } from '@/lib/pdfData';

// ---------------------------------------------------------------------------
// Monochrome palette — @react-pdf/renderer uses its own StyleSheet,
// not Tailwind/DS tokens. Only black/grey values; zero color in the PDF.
//
// IMPORTANT: Never use textTransform in @react-pdf/renderer — it interacts
// badly with letterSpacing, inserting spaces inside words. Always use
// .toUpperCase() in JS. Never use unicode symbols (emoji, ℹ, ↗) — Helvetica
// doesn't have those glyphs and they render as garbage.
// ---------------------------------------------------------------------------

const BLACK = '#18181b';     // zinc-900 — titles, names, headings
const MID = '#71717a';       // zinc-500 — labels, metadata, constraints
const LIGHT = '#a1a1aa';     // zinc-400 — period labels, intensity, footer
const DARK_GREY = '#52525b'; // zinc-600 — underlined link text
const RULE = '#d4d4d8';      // zinc-300 — horizontal rules

// ---------------------------------------------------------------------------
// Styles — no textTransform anywhere, no letterSpacing > 1
// ---------------------------------------------------------------------------

const s = StyleSheet.create({
  // Page
  page: {
    padding: 40,
    fontFamily: 'Helvetica',
    fontSize: 10,
    color: BLACK,
  },
  footer: {
    position: 'absolute',
    bottom: 30,
    left: 40,
    right: 40,
    textAlign: 'center',
    fontSize: 7,
    color: LIGHT,
  },

  // Header
  brand: {
    fontSize: 8,
    letterSpacing: 1,
    color: MID,
    marginBottom: 8,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
  },
  subtitle: {
    fontSize: 10,
    color: MID,
    marginTop: 3,
    marginBottom: 12,
  },
  rule: {
    borderBottomWidth: 1,
    borderBottomColor: RULE,
    marginBottom: 14,
  },

  // Days
  dayHeader: {
    fontSize: 10,
    fontWeight: 'bold',
    letterSpacing: 1,
    marginTop: 14,
  },
  dayMeta: {
    fontSize: 8,
    color: LIGHT,
    marginBottom: 6,
  },
  dashedRule: {
    borderBottomWidth: 0.5,
    borderBottomColor: RULE,
    borderBottomStyle: 'dashed',
    marginTop: 10,
    marginBottom: 10,
  },

  // Blocks
  blockWrap: {
    marginBottom: 8,
  },
  periodLabel: {
    fontSize: 7,
    letterSpacing: 0.5,
    color: LIGHT,
    marginBottom: 1,
  },
  specialistLabel: {
    fontSize: 7,
    fontWeight: 'bold',
    letterSpacing: 1,
    color: MID,
    marginBottom: 1,
  },
  blockName: {
    fontSize: 11,
    fontWeight: 'bold',
    marginBottom: 1,
  },
  blockMeta: {
    fontSize: 9,
    color: MID,
    marginBottom: 2,
  },
  constraintInline: {
    fontSize: 8,
    color: MID,
    paddingLeft: 8,
    fontStyle: 'italic',
    marginBottom: 6,
  },
  bufferWrap: {
    marginBottom: 4,
  },
  bufferBlock: {
    fontSize: 10,
    color: MID,
    fontStyle: 'italic',
    marginBottom: 6,
  },

  // Venue Links
  venueLinksWrap: {
    marginTop: 16,
  },
  sectionTitle: {
    fontSize: 9,
    fontWeight: 'bold',
    letterSpacing: 1,
    marginTop: 16,
    marginBottom: 8,
  },
  linksSubHeader: {
    fontSize: 10,
    fontWeight: 'bold',
    marginBottom: 4,
    marginTop: 8,
  },
  venueRow: {
    marginBottom: 8,
  },
  venueNameRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  venueName: {
    fontSize: 10,
    fontWeight: 'bold',
  },
  venueDetail: {
    fontSize: 9,
    color: MID,
  },
  venueLink: {
    fontSize: 7,
    color: DARK_GREY,
    textDecoration: 'underline',
    marginBottom: 8,
  },
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Clean duration: "4.0h" → "4h", "6.0h" → "6h" */
function cleanDuration(d: string | null): string | null {
  if (!d) return null;
  return d.replace(/\.0h$/, 'h');
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function TripHeader({ data }: { data: TripPdfData }) {
  const metaParts = [data.dates, data.travelers].filter(Boolean).join(' / ');

  return (
    <View>
      <Text style={s.brand}>NOMADIC</Text>
      <Text style={s.title}>{data.destination}</Text>
      {metaParts || data.budget ? (
        <Text style={s.subtitle}>
          {metaParts}
          {metaParts && data.budget ? ' / ' : ''}
          {data.budget ? `Budget ${data.budget}` : ''}
        </Text>
      ) : null}
      <View style={s.rule} />
    </View>
  );
}

function BlockRow({ block }: { block: PdfBlockData }) {
  // Only price + duration in block meta — intensity lives on the day header only
  const metaParts = [block.priceDisplay, cleanDuration(block.duration)].filter(Boolean).join(' / ');

  // Buffer blocks — single italic line
  if (block.isBuffer) {
    return (
      <View style={s.bufferWrap}>
        <Text style={s.bufferBlock}>
          {block.summary}
          {block.bufferReason ? ` -- ${block.bufferReason}` : ''}
        </Text>
        {block.logisticsDetails ? <Text style={s.constraintInline}>{block.logisticsDetails}</Text> : null}
      </View>
    );
  }

  return (
    <View style={s.blockWrap}>
      <Text style={s.periodLabel}>{block.period.toUpperCase()}</Text>
      {block.specialistType ? (
        <Text style={s.specialistLabel}>{block.specialistType.toUpperCase()}</Text>
      ) : null}
      <Text style={s.blockName}>{block.summary}</Text>
      {metaParts ? <Text style={s.blockMeta}>{metaParts}</Text> : null}
      {block.hotelName ? <Text style={s.blockMeta}>{'Stay: '}{block.hotelName}</Text> : null}
      {block.constraintNotes.map((note, i) => (
        <Text key={i} style={s.constraintInline}>
          {'-- '}{note}
        </Text>
      ))}
    </View>
  );
}

function DaySection({ day, isFirst }: { day: PdfDaySection; isFirst: boolean }) {
  // Only show intensity if moderate or challenging — "light" adds no value
  const intensityLabel = day.intensity && day.intensity !== 'light'
    ? day.intensity.charAt(0).toUpperCase() + day.intensity.slice(1)
    : null;

  const headerText = [
    `DAY ${day.dayNumber}`,
    day.date ? day.date.toUpperCase() : null,
  ].filter(Boolean).join('  /  ');

  return (
    <View wrap={false}>
      {!isFirst && <View style={s.dashedRule} />}
      <Text style={s.dayHeader}>{headerText}</Text>
      {(intensityLabel || day.label) ? (
        <Text style={s.dayMeta}>
          {[intensityLabel, day.label].filter(Boolean).join('  /  ')}
        </Text>
      ) : null}
      {day.blocks.map((block, i) => (
        <BlockRow key={i} block={block} />
      ))}
    </View>
  );
}

function HotelLinkRow({ hotel }: { hotel: PdfHotelLink }) {
  return (
    <View style={s.venueRow}>
      <View style={s.venueNameRow}>
        <Link src={hotel.url}>
          <Text style={s.venueName}>{hotel.title}</Text>
        </Link>
        {hotel.pricePerNight ? <Text style={s.venueDetail}>{'  /  '}{hotel.pricePerNight}</Text> : null}
      </View>
      <Link src={hotel.url}>
        <Text style={s.venueLink}>Open in Google Travel</Text>
      </Link>
    </View>
  );
}

function ActivityLinkRow({ activity }: { activity: PdfActivityLink }) {
  return (
    <View style={s.venueRow}>
      <View style={s.venueNameRow}>
        <Link src={activity.url}>
          <Text style={s.venueName}>{activity.name}</Text>
        </Link>
        {activity.meta ? <Text style={s.venueDetail}>{'  /  '}{activity.meta}</Text> : null}
      </View>
      <Link src={activity.url}>
        <Text style={s.venueLink}>Open in Google Maps</Text>
      </Link>
    </View>
  );
}

function VenueLinks({ hotels, activities }: { hotels: PdfHotelLink[]; activities: PdfActivityLink[] }) {
  if (hotels.length === 0 && activities.length === 0) return null;

  return (
    <View style={s.venueLinksWrap} break>
      <Text style={s.sectionTitle}>VENUE LINKS</Text>
      {hotels.length > 0 ? (
        <>
          <Text style={s.linksSubHeader}>Hotels</Text>
          {hotels.map((h, i) => (
            <HotelLinkRow key={i} hotel={h} />
          ))}
        </>
      ) : null}
      {activities.length > 0 ? (
        <>
          <Text style={s.linksSubHeader}>Activities</Text>
          {activities.map((a, i) => (
            <ActivityLinkRow key={i} activity={a} />
          ))}
        </>
      ) : null}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Main document
// ---------------------------------------------------------------------------

export function TripPdfDocument({ data }: { data: TripPdfData }) {
  return (
    <Document>
      <Page size="A4" style={s.page}>
        <TripHeader data={data} />

        {data.days.map((day, i) => (
          <DaySection key={day.dayNumber} day={day} isFirst={i === 0} />
        ))}

        <VenueLinks hotels={data.hotelLinks} activities={data.activityLinks} />

        <Text style={s.footer} fixed render={({ pageNumber, totalPages }) =>
          `Generated by Nomadic / ${pageNumber} of ${totalPages}`
        } />
      </Page>
    </Document>
  );
}
