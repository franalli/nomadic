import { Document, Link, Page, Text, View } from '@react-pdf/renderer';

import type { PdfActivityLink, PdfBlockData, PdfDaySection, PdfHotelLink, TripPdfData } from '@/lib/pdfData';

import { cleanDuration, s } from './tripPdfStyles';

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
        <Text key={`${note}-${i}`} style={s.constraintInline}>
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
        <BlockRow key={`${block.summary}-${i}`} block={block} />
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
          {hotels.map((h) => (
            <HotelLinkRow key={h.url} hotel={h} />
          ))}
        </>
      ) : null}
      {activities.length > 0 ? (
        <>
          <Text style={s.linksSubHeader}>Activities</Text>
          {activities.map((a) => (
            <ActivityLinkRow key={a.url} activity={a} />
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
