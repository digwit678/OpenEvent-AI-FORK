'use client'

import { useParams, useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'

interface MenuItem {
  course: string
  description: string
  dietary: string[]
  allergens: string[]
}

interface Menu {
  name: string
  price_per_person: number
  courses: MenuItem[]
  beverages_included: string[]
  minimum_order: number
  description: string
  context?: {
    room?: string
    date?: string
  }
}

export default function CateringMenuPage() {
  const params = useParams()
  const searchParams = useSearchParams()
  const menuSlug = params.menu as string
  const room = searchParams.get('room')
  const date = searchParams.get('date')
  const [menu, setMenu] = useState<Menu | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const queryParams = new URLSearchParams()
    if (room) queryParams.append('room', room)
    if (date) queryParams.append('date', date)

    fetch(`http://localhost:8000/api/test-data/catering/${menuSlug}?${queryParams}`)
      .then(res => {
        if (!res.ok) throw new Error('Menu not found')
        return res.json()
      })
      .then(data => {
        setMenu(data)
        setLoading(false)
      })
      .catch(err => {
        console.error('Failed to load menu:', err)
        setLoading(false)
      })
  }, [menuSlug, room, date])

  if (loading) {
    return (
      <div className="container mx-auto p-8">
        <div className="text-center">Loading menu details...</div>
      </div>
    )
  }

  if (!menu) {
    return (
      <div className="container mx-auto p-8">
        <div className="text-center">Menu not found</div>
      </div>
    )
  }

  return (
    <div className="container mx-auto p-8 max-w-4xl">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2">{menu.name}</h1>
        <div className="text-2xl text-blue-600 font-semibold mb-4">
          CHF {menu.price_per_person} per person
          {menu.minimum_order > 1 && (
            <span className="text-lg text-gray-600 ml-2">
              (minimum {menu.minimum_order} guests)
            </span>
          )}
        </div>

        {/* Context if provided */}
        {(room || date) && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
            {room && (
              <div className="text-gray-700">
                <span className="font-semibold">Selected room:</span> {room}
              </div>
            )}
            {date && (
              <div className="text-gray-700">
                <span className="font-semibold">Event date:</span> {date}
              </div>
            )}
          </div>
        )}

        <p className="text-lg text-gray-700">{menu.description}</p>
      </div>

      {/* Menu Courses */}
      <div className="mb-8">
        <h2 className="text-2xl font-semibold mb-6">Menu Courses</h2>
        <div className="space-y-6">
          {menu.courses.map((course, idx) => (
            <div key={idx} className="bg-white border rounded-lg p-6 shadow-sm">
              <h3 className="text-xl font-semibold mb-3 text-gray-900">
                {course.course}
              </h3>
              <p className="text-gray-700 mb-4 leading-relaxed">
                {course.description}
              </p>

              {/* Dietary tags */}
              {course.dietary.length > 0 && (
                <div className="flex gap-2 flex-wrap">
                  {course.dietary.map((diet) => (
                    <span
                      key={diet}
                      className="px-3 py-1 bg-green-100 text-green-700 rounded-full text-sm font-medium"
                    >
                      {diet}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Beverages */}
      <div className="mb-8">
        <h2 className="text-2xl font-semibold mb-4">Beverages Included</h2>
        <div className="bg-gray-50 rounded-lg p-6">
          <ul className="space-y-2">
            {menu.beverages_included.map((beverage, idx) => (
              <li key={idx} className="flex items-start">
                <span className="text-blue-500 mr-3 mt-1">•</span>
                <span className="text-gray-700">{beverage}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-12 text-center">
        <p className="text-gray-600 mb-4">
          Return to your booking conversation to select this menu
        </p>
        <a
          href="/info/catering"
          className="text-blue-600 hover:underline"
        >
          ← View all catering options
        </a>
      </div>
    </div>
  )
}
