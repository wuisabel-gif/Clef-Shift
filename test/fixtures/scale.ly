\version "2.24.0"
\paper { oddFooterMarkup = ##f oddHeaderMarkup = ##f scoreTitleMarkup = ##f }
\header { tagline = ##f }
\score {
  \new Staff {
    \clef treble
    \time 4/4
    % Known pitches: a one-octave G major scale up and a few extras
    g'4 a'4 b'4 c''4 | d''4 e''4 fis''4 g''4 |
    a''4 b''4 c'''4 b''4 | a''4 g''4 fis''4 e''4 |
  }
  \layout { }
}
