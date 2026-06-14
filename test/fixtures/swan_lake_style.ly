\version "2.24.0"
% A reproduction of the *conditions* of the Swan Lake fixture: a multi-system
% violin page surrounded by non-note metadata (title, composer, instrument
% text, tempo, chord symbols, dynamics, bar numbers) so we can test that the
% detector reads only the staff and never the metadata. NOT the exact
% Tchaikovsky page -- that remains the user's real file.
\header {
  title = "SWAN LAKE"
  subtitle = \markup \center-column { "Act. 2, N. 10 \"Scene\"" "Violin Solo" }
  composer = \markup \right-column { "Piotr Ilitch Tchaikovski" "(1840 - 1893)" }
  tagline = ##f
}

harmonies = \chordmode {
  b2:m e:m | b1:m | b2:m e:m | b1:m |
  e:m a:7 | d2 a:7 | fis1:m | b1:m |
  e:m a:7 | d2 a:7 | fis1:m | b1:m |
  b2:m e:m | b1:m | a2 d | b1:m |
}

melody = \relative c'' {
  \clef treble \key d \major \time 4/4 \tempo "Moderato"
  \set Staff.instrumentName = #"Violin "
  fis4\p -\markup \italic "espressivo" b8 a fis4. e8 | d2 fis4 e |
  d4 fis8 e d4. cis8 | b2 d4 cis |
  b4 d8 cis b4. a8 | g2 b4 a |
  fis4 a8 g fis4. e8 | d2. r4 |
  cis'4\< d8 cis b4. a8 | g2 b4 a |
  fis4 a8 g fis4. e8\! | d2.\f r4 |
  b'4 a8 g fis4. e8 | d2 fis4 e |
  d4 cis8 b a4. g8 | fis1 |
}

\score {
  <<
    \new ChordNames \harmonies
    \new Staff \melody
  >>
  \layout { }
}
