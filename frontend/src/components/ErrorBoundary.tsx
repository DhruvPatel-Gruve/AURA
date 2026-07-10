import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'
import { logger } from '../utils/logger'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

/**
 * Top-level render-error catch. Without this, any uncaught error thrown
 * during render (a malformed API response, a bad prop, a third-party
 * component throwing) unmounts the entire React tree and leaves the user
 * staring at a blank white page with zero recovery path.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    logger.error('render error', error, { componentStack: info.componentStack })
  }

  private reload = () => {
    this.setState({ hasError: false, error: null })
    window.location.reload()
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="min-h-screen flex items-center justify-center bg-canvas p-6">
        <div className="max-w-md w-full text-center space-y-4">
          <AlertTriangle className="mx-auto h-8 w-8 text-faint" />
          <h1 className="text-lg font-semibold text-ink">
            Something went wrong
          </h1>
          <p className="text-sm text-body">
            AURA hit an unexpected error and couldn't render this page. Reloading usually fixes it —
            if it keeps happening, let your admin know.
          </p>
          {this.state.error && (
            <p className="text-xs font-mono text-faint break-words">
              {this.state.error.message}
            </p>
          )}
          <button onClick={this.reload} className="btn-primary mx-auto">
            Reload AURA
          </button>
        </div>
      </div>
    )
  }
}
