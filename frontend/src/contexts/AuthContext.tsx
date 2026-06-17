import {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
  useCallback,
} from 'react'
import type { User } from '../types'
import { authApi } from '../services/api'

interface AuthContextType {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (token: string, user?: User) => void
  logout: () => void
  refreshProfile: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('access_token')
    const savedUser = localStorage.getItem('user')

    if (token && savedUser) {
      try {
        setUser(JSON.parse(savedUser))
        authApi
          .getProfile()
          .then((profile) => {
            setUser(profile)
            localStorage.setItem('user', JSON.stringify(profile))
          })
          .catch(() => {
            localStorage.removeItem('access_token')
            localStorage.removeItem('user')
            setUser(null)
          })
      } catch {
        localStorage.removeItem('access_token')
        localStorage.removeItem('user')
      }
    }
    setIsLoading(false)
  }, [])

  const login = useCallback((token: string, userData?: User) => {
    localStorage.setItem('access_token', token)
    if (userData) {
      setUser(userData)
      localStorage.setItem('user', JSON.stringify(userData))
    }
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('user')
    setUser(null)
  }, [])

  const refreshProfile = useCallback(async () => {
    try {
      const profile = await authApi.getProfile()
      setUser(profile)
      localStorage.setItem('user', JSON.stringify(profile))
    } catch {
      logout()
    }
  }, [logout])

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        logout,
        refreshProfile,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
