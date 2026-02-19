/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { apiClient, setAuthFailureHandler, setAuthToken, type AuthUser, type UserRole } from '@/lib/api'

const TOKEN_STORAGE_KEY = 'workforyou.auth.token'

interface AuthContextValue {
  user: AuthUser | null
  token: string | null
  isLoading: boolean
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, role?: UserRole) => Promise<void>
  logout: () => void
  tryDemo: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

// Manages auth state (token + user) and exposes login/logout/register actions via context.
export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(localStorage.getItem(TOKEN_STORAGE_KEY))
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    setAuthToken(token)
  }, [token])

  useEffect(() => {
    setAuthFailureHandler(() => {
      localStorage.removeItem(TOKEN_STORAGE_KEY)
      setToken(null)
      setUser(null)
    })
    return () => setAuthFailureHandler(null)
  }, [])

  useEffect(() => {
    async function loadCurrentUser() {
      if (!token) {
        setUser(null)
        setIsLoading(false)
        return
      }

      try {
        const currentUser = await apiClient.me()
        setUser(currentUser)
      } catch {
        localStorage.removeItem(TOKEN_STORAGE_KEY)
        setToken(null)
        setUser(null)
      } finally {
        setIsLoading(false)
      }
    }

    void loadCurrentUser()
  }, [token])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      isLoading,
      isAuthenticated: Boolean(token && user),
      login: async (email, password) => {
        const response = await apiClient.login({ email, password })
        localStorage.setItem(TOKEN_STORAGE_KEY, response.access_token)
        setToken(response.access_token)
        setUser(response.user)
      },
      register: async (email, password, role = 'employee') => {
        const response = await apiClient.register({ email, password, role })
        localStorage.setItem(TOKEN_STORAGE_KEY, response.access_token)
        setToken(response.access_token)
        setUser(response.user)
      },
      logout: () => {
        localStorage.removeItem(TOKEN_STORAGE_KEY)
        setToken(null)
        setUser(null)
      },
      tryDemo: async () => {
        await apiClient.seedDemo()
        const response = await apiClient.login({ email: 'owner@demo.com', password: 'demo' })
        localStorage.setItem(TOKEN_STORAGE_KEY, response.access_token)
        setToken(response.access_token)
        setUser(response.user)
      },
    }),
    [isLoading, token, user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// Hook to access auth state and actions — must be used inside AuthProvider.
export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider')
  }
  return context
}
