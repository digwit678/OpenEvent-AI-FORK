'use client'

import { useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'

interface VisitSlot {
  date: string
  time: string
  available: boolean
  room?: string
}

interface VisitInfo {
  title: string
  duration: string
  includes: string[]
  meeting_point: string
  what_to_expect: string[]
  booking_policy: string
}

export default function SiteVisitsPage() {
  const searchParams = useSearchParams()
  const room = searchParams.get('room')
  const dateRange = searchParams.get('dates')
  const [visitInfo, setVisitInfo] = useState<VisitInfo | null>(null)
  const [availableSlots, setAvailableSlots] = useState<VisitSlot[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Load visit information
    const info: VisitInfo = {
      title: "Site Visit at The Atelier",
      duration: "60 minutes",
      includes: [
        "Guided tour of all event spaces",
        "Room setup demonstrations",
        "Technical capabilities overview",
        "Catering tasting options (if requested)",
        "Q&A with event coordinator",
      ],
      meeting_point: "Main reception - Bahnhofstrasse 10, 8001 Zürich",
      what_to_expect: [
        "Meet your dedicated event coordinator",
        "Tour the requested room(s) and alternatives",
        "See different layout configurations",
        "Review technical equipment and capabilities",
        "Discuss your specific event requirements",
        "Get answers to all your questions",
      ],
      booking_policy: "Site visits are complimentary and can be scheduled Monday-Friday, 9:00-17:00. Weekend visits may be arranged for confirmed bookings.",
    }
    setVisitInfo(info)

    // Generate available slots (mock data)
    const slots: VisitSlot[] = []
    const today = new Date()
    for (let i = 1; i <= 14; i++) {
      const date = new Date(today)
      date.setDate(today.getDate() + i)

      // Skip weekends
      if (date.getDay() === 0 || date.getDay() === 6) continue

      // Morning and afternoon slots
      slots.push({
        date: date.toISOString().split('T')[0],
        time: "10:00-11:00",
        available: true,
        room: room || undefined,
      })
      slots.push({
        date: date.toISOString().split('T')[0],
        time: "14:00-15:00",
        available: Math.random() > 0.3, // Some slots unavailable
        room: room || undefined,
      })
    }

    setAvailableSlots(slots)
    setLoading(false)
  }, [room, dateRange])

  if (loading || !visitInfo) {
    return (
      <div className="container mx-auto p-8">
        <div className="text-center">Loading site visit information...</div>
      </div>
    )
  }

  return (
    <div className="container mx-auto p-8 max-w-6xl">
      <h1 className="text-3xl font-bold mb-8">{visitInfo.title}</h1>

      {room && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
          <span className="font-semibold">Viewing:</span> {room}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-12">
        {/* Visit Information */}
        <div className="space-y-6">
          <div>
            <h2 className="text-2xl font-semibold mb-4">What's Included</h2>
            <ul className="space-y-2">
              {visitInfo.includes.map((item, idx) => (
                <li key={idx} className="flex items-start">
                  <span className="text-green-500 mr-2 mt-1">✓</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h2 className="text-2xl font-semibold mb-4">What to Expect</h2>
            <ol className="space-y-2">
              {visitInfo.what_to_expect.map((item, idx) => (
                <li key={idx} className="flex items-start">
                  <span className="font-semibold mr-2">{idx + 1}.</span>
                  <span>{item}</span>
                </li>
              ))}
            </ol>
          </div>

          <div className="bg-gray-50 rounded-lg p-6">
            <h3 className="font-semibold mb-2">Duration</h3>
            <p>{visitInfo.duration}</p>

            <h3 className="font-semibold mb-2 mt-4">Meeting Point</h3>
            <p>{visitInfo.meeting_point}</p>

            <h3 className="font-semibold mb-2 mt-4">Booking Policy</h3>
            <p className="text-sm text-gray-600">{visitInfo.booking_policy}</p>
          </div>
        </div>

        {/* Available Time Slots */}
        <div>
          <h2 className="text-2xl font-semibold mb-4">Available Time Slots</h2>
          <div className="bg-white border rounded-lg shadow-sm overflow-hidden">
            <div className="max-h-96 overflow-y-auto">
              {availableSlots.map((slot, idx) => {
                const date = new Date(slot.date)
                const dateStr = date.toLocaleDateString('en-US', {
                  weekday: 'long',
                  month: 'long',
                  day: 'numeric',
                })

                return (
                  <div
                    key={idx}
                    className={`p-4 border-b hover:bg-gray-50 ${
                      !slot.available ? 'opacity-50' : ''
                    }`}
                  >
                    <div className="flex justify-between items-center">
                      <div>
                        <div className="font-medium">{dateStr}</div>
                        <div className="text-gray-600">{slot.time}</div>
                      </div>
                      <div>
                        {slot.available ? (
                          <span className="px-3 py-1 bg-green-100 text-green-700 rounded-full text-sm">
                            Available
                          </span>
                        ) : (
                          <span className="px-3 py-1 bg-gray-100 text-gray-500 rounded-full text-sm">
                            Unavailable
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>

      {/* How to Book */}
      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6">
        <h2 className="text-xl font-semibold mb-3">How to Book Your Visit</h2>
        <p>
          Simply return to your booking conversation and let us know which time slot works best for you.
          You can say something like "I'd like to visit on Tuesday at 10:00" or select from the options
          we've proposed.
        </p>
      </div>
    </div>
  )
}