\version "2.24.0"
\paper { oddFooterMarkup = ##f oddHeaderMarkup = ##f scoreTitleMarkup = ##f paper-width = 11\in line-width = 10\in indent = 0 }
\header { tagline = ##f }
\score {
  \new Staff \with { instrumentName = "Flauta" } {
    \clef treble \key aes \major \time 4/4 \tempo 4 = 101
    r8 aes'8[ c''8 ees''8] des''2 | ees''1 |
  }
  \layout { }
}
