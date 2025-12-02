'use client'

import { useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import Link from 'next/link'

interface MenuSummary {
  name: string
  slug: string
  price_per_person: number
  summary: string
  dietary_options: string[]
  availability_window?: string | string[]
}

export default function CateringCateringCatalogPage() {
  const searchParams = useSearchParams()
  const [menus, setMenus] = useState<MenuSummary[]>([])
  const [loading, setLoading] = useState(true)

  // Extract all query parameters for filtering
  const queryFilters = {
    month: searchParams.get('month'),
    vegetarian: searchParams.get('vegetarian'),
    vegan: searchParams.get('vegan'),
    courses: searchParams.get('courses'),
    wine_pairing: searchParams.get('wine_pairing'),
  }

  // Build filter description for display
  const getFilterDescription = () => {
    const parts: string[] = []

    if (queryFilters.month) {
      parts.push(`in ${queryFilters.month.charAt(0).toUpperCase() + queryFilters.month.slice(1)}`)
    }
    if (queryFilters.vegetarian === 'true') {
      parts.push('vegetarian')
    }
    if (queryFilters.vegan === 'true') {
      parts.push('vegan')
    }
    if (queryFilters.courses) {
      parts.push(`${queryFilters.courses}-course`)
    }
    if (queryFilters.wine_pairing === 'true') {
      parts.push('with wine pairing')
    }

    return parts.length > 0 ? parts.join(', ') : null
  }

  useEffect(() => {
    // Build URL with all query parameters
    const params = new URLSearchParams()
    if (queryFilters.month) params.append('month', queryFilters.month)
    if (queryFilters.vegetarian) params.append('vegetarian', queryFilters.vegetarian)
    if (queryFilters.vegan) params.append('vegan', queryFilters.vegan)
    if (queryFilters.courses) params.append('courses', queryFilters.courses)
    if (queryFilters.wine_pairing) params.append('wine_pairing', queryFilters.wine_pairing)

    const url = `http://localhost:8000/api/test-data/catering?${params.toString()}`

    fetch(url)
      .then(res => res.json())
      .then(data => {
        setMenus(data)
        setLoading(false)
      })
      .catch(err => {
        console.error('Failed to load menus:', err)
        setLoading(false)
      })
  }, [queryFilters.month, queryFilters.vegetarian, queryFilters.vegan, queryFilters.courses, queryFilters.wine_pairing])

  if (loading) {
    return (
      <div className="container mx-auto p-8">
        <div className="text-center">Loading catering options...</div>
      </div>
    )
  }

  return (
    <div className="container mx-auto p-8 max-w-6xl">
      <h1 className="text-3xl font-bold mb-8">Catering Menu Options</h1>

      {/* Display active filters */}
      {getFilterDescription() && (
        <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <div className="text-sm font-semibold text-blue-900 mb-1">Active Filters:</div>
          <div className="text-blue-800">{getFilterDescription()}</div>
        </div>
      )}

      {menus.length === 0 && !loading && (
        <div className="text-center p-8 text-gray-600">
          No menus match your filters. Try adjusting your criteria.
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {menus.map((menu) => (
          <Link
            key={menu.slug}
            href={`/info/catering/${menu.slug}`}
            className="block border rounded-lg p-6 hover:shadow-lg transition-shadow bg-white"
          >
            <h2 className="text-xl font-semibold mb-2">{menu.name}</h2>
            <div className="text-2xl font-bold text-blue-600 mb-3">
              CHF {menu.price_per_person} per person
            </div>
            <p className="text-gray-700 mb-4">{menu.summary}</p>
            {menu.dietary_options.length > 0 && (
              <div className="flex gap-2">
                {menu.dietary_options.map((diet) => (
                  <span
                    key={diet}
                    className="px-3 py-1 bg-green-100 text-green-700 rounded-full text-sm"
                  >
                    {diet}
                  </span>
                ))}
              </div>
            )}
          </Link>
        ))}
      </div>
    </div>
  )
}
